# One Dockerfile, three targets. Each service image gets only what it needs, and none of them
# contains database settings at build time (they come from the environment at run time).
#   app        -> api, app-worker, scheduler
#   exec       -> exec-worker (drives sandbox-docker through the Docker SDK, a normal dependency)
#   inference  -> inference-worker (adds PyTorch for the CPU, RT-DETR and YuNet)

FROM ghcr.io/astral-sh/uv:0.13 AS uv

FROM python:3.12-slim AS deps
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1     UV_COMPILE_BYTECODE=1     UV_LINK_MODE=copy     UV_PROJECT_ENVIRONMENT=/opt/venv     PATH=/opt/venv/bin:$PATH
WORKDIR /srv
# Every process finds app, domain_core, workers and cli however it was started: the celery command
# only puts its folder on the path while loading, so a package first imported later inside a task
# (domain_core for the sweeper) was otherwise not found.
ENV PYTHONPATH=/srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN useradd --uid 10000 --no-create-home appuser

FROM deps AS base
COPY . .
USER appuser

FROM base AS app

FROM base AS exec

# PyTorch and the models come before the source, so a code change doesn't reinstall them.
FROM deps AS inference
RUN uv sync --frozen --no-dev --group inference --no-install-project --no-cache
# The models, pinned: RT-DETR r18 at a fixed revision; YuNet and SFace at a fixed commit, with
# their hashes.
ARG RTDETR_REVISION=ac77a11ff0170a41b771c03264987f8ce2b0d753
ARG YUNET_URL=https://github.com/opencv/opencv_zoo/raw/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
ARG YUNET_SHA256=8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
ARG SFACE_URL=https://github.com/opencv/opencv_zoo/raw/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
ARG SFACE_SHA256=0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('PekingU/rtdetr_r18vd', revision='${RTDETR_REVISION}', local_dir='/opt/models/rtdetr_r18vd')"  && python -c "import hashlib, urllib.request; d = urllib.request.urlopen('${YUNET_URL}', timeout=60).read(); assert hashlib.sha256(d).hexdigest() == '${YUNET_SHA256}', 'YuNet hash'; open('/opt/models/face_detection_yunet_2023mar.onnx', 'wb').write(d)"
RUN python -c "import hashlib, urllib.request; d = urllib.request.urlopen('${SFACE_URL}', timeout=120).read(); assert hashlib.sha256(d).hexdigest() == '${SFACE_SHA256}', 'SFace hash'; open('/opt/models/face_recognition_sface_2021dec.onnx', 'wb').write(d)"
ENV HF_HUB_OFFLINE=1
COPY . .
USER appuser
