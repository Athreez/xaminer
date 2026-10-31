import { IDBFactory } from "fake-indexeddb";
import { describe, expect, it } from "vitest";

import { MAX_WAITING, newPicture, PictureQueue, type Picture, type Purpose } from "./pictures";

const A = "attempt-1";

async function queue(statuses: number[] = []) {
  const sent: Picture[] = [];
  const q = await PictureQueue.open(
    A,
    async (p) => {
      sent.push(p);
      return statuses.shift() ?? 204;
    },
    new IDBFactory(),
  );
  return { q, sent };
}

const picture = (purpose: Purpose, at: number) => ({
  ...newPicture(
    A,
    purpose === "PERIODIC" || purpose === "LEFT_PAGE" ? "SCREEN" : "CAMERA",
    purpose,
    new Blob(["x"]),
    purpose === "EVENT" ? "event-1" : undefined,
  ),
  takenAt: at,
});

describe("picture queue", () => {
  it("sends event pictures first and spot checks last", async () => {
    const { q, sent } = await queue();
    await q.add(picture("SPOT_CHECK", 1));
    await q.add(picture("PERIODIC", 2));
    await q.add(picture("EVENT", 3));
    await q.add(picture("LEFT_PAGE", 4));
    while ((await q.sendNext("t")) === "sent");
    expect(sent.map((p) => p.purpose)).toEqual(["EVENT", "LEFT_PAGE", "PERIODIC", "SPOT_CHECK"]);
    expect(await q.waiting()).toEqual([]);
  });

  it("keeps a picture through network trouble and an expired token, drops refused ones", async () => {
    const { q } = await queue([0, 401, 503, 422]);
    await q.add(picture("EVENT", 1));
    expect(await q.sendNext("t")).toBe("later");
    expect(await q.sendNext("t")).toBe("token");
    expect(await q.sendNext("t")).toBe("later");
    expect(await q.waiting()).toHaveLength(1);
    expect(await q.sendNext("t")).toBe("sent"); // 422: it would never pass
    expect(await q.waiting()).toHaveLength(0);
  });

  it("forgets everything once the attempt is closed", async () => {
    const { q } = await queue([409]);
    await q.add(picture("EVENT", 1));
    await q.add(picture("PERIODIC", 2));
    expect(await q.sendNext("t")).toBe("closed");
    expect(await q.waiting()).toEqual([]);
  });

  it("drops the oldest spot checks first when too many wait", async () => {
    const { q } = await queue();
    await q.add(picture("EVENT", 0));
    for (let i = 1; i <= MAX_WAITING + 4; i++) await q.add(picture("SPOT_CHECK", i));
    const waiting = await q.waiting();
    expect(waiting).toHaveLength(MAX_WAITING);
    expect(waiting[0]!.purpose).toBe("EVENT");
    expect(waiting[1]!.takenAt).toBe(6); // 1 to 5 went
  });
});
