import { describe, expect, it } from "vitest";

import { nextSelection } from "./MultiSelect";

describe("nextSelection", () => {
  it("adds a value when under the max", () => {
    expect(nextSelection(["a"], "b", 3)).toEqual(["a", "b"]);
  });

  it("removes a value that is already selected", () => {
    expect(nextSelection(["a", "b"], "a", 3)).toEqual(["b"]);
  });

  it("ignores a new value once the max is reached (no-op: same reference)", () => {
    const selected = ["a", "b", "c"];
    expect(nextSelection(selected, "d", 3)).toBe(selected);
  });

  it("still allows deselecting while at the max", () => {
    expect(nextSelection(["a", "b", "c"], "b", 3)).toEqual(["a", "c"]);
  });

  it("has no cap when max is undefined", () => {
    expect(nextSelection(["a", "b", "c"], "d")).toEqual(["a", "b", "c", "d"]);
  });
});
