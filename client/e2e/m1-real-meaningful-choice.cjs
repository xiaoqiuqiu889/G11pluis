const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const FRONTEND = process.env.G1N_FRONTEND_URL || "http://127.0.0.1:5173";
const BACKEND = process.env.G1N_BACKEND_URL || "http://127.0.0.1:8000";
const SCENE_ID = "photo_lab_2008";
const TIMEOUT = 20_000;

const BRANCHES = [
  {
    name: "split",
    testId: "photo-choice-split",
    targetId: "arash",
    endingId: "shared_secret",
    seeds: ["photo_in_book", "photo_in_pocket"],
    consequencePattern: /\u4e00\u4eba\u4e00\u5f20|\u5404\u81ea|\u963f\u62c9\u4ec0.*\u4e00\u5f20|\u4e00\u5f20.*\u963f\u62c9\u4ec0/,
  },
  {
    name: "keep-both",
    testId: "photo-choice-keep-both",
    targetId: "leila",
    endingId: "one_sided_memory",
    seeds: ["both_photos_with_one"],
    consequencePattern: /\u4e24\u5f20.*\u83b1\u62c9|\u83b1\u62c9.*\u4e24\u5f20|\u90fd\u7559|\u5168\u90e8\u7559\u4e0b/,
  },
];

function isPostTo(response, pathPattern) {
  const url = new URL(response.url());
  return response.request().method() === "POST" && pathPattern.test(url.pathname);
}

function exactSorted(values) {
  return [...values].sort();
}

async function jsonResponse(response, label) {
  assert.equal(response.status(), 200, `${label} should return HTTP 200`);
  return response.json();
}

async function runBranch(browser, branch) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: "zh-CN",
  });
  const page = await context.newPage();

  try {
    const createResponsePromise = page.waitForResponse(
      (response) => isPostTo(response, /^\/v1\/runs\/?$/),
      { timeout: TIMEOUT },
    );

    await page.goto(`${FRONTEND}/scene/${SCENE_ID}`, {
      waitUntil: "domcontentloaded",
      timeout: TIMEOUT,
    });

    const createResponse = await createResponsePromise;
    const createBody = await jsonResponse(createResponse, `${branch.name} create run`);
    const runId = createBody?.run?.runId;
    assert.ok(runId, `${branch.name} create response should include run.runId`);

    const choice = page.getByTestId(branch.testId);
    await assert.doesNotReject(
      choice.waitFor({ state: "visible", timeout: TIMEOUT }),
      `${branch.name} meaningful choice should become visible`,
    );
    await assert.doesNotReject(
      page.waitForFunction(
        (testId) => {
          const element = document.querySelector(`[data-testid="${testId}"]`);
          return element instanceof HTMLButtonElement && !element.disabled;
        },
        branch.testId,
        { timeout: TIMEOUT },
      ),
      `${branch.name} meaningful choice should become enabled after run setup`,
    );
    assert.equal(await choice.isEnabled(), true, `${branch.name} choice should be enabled`);

    const actionResponsePromise = page.waitForResponse(
      (response) =>
        isPostTo(response, new RegExp(`^/v1/runs/${runId}/actions/?$`)),
      { timeout: TIMEOUT },
    );

    await choice.click();
    const actionResponse = await actionResponsePromise;
    const actionRequest = actionResponse.request().postDataJSON();
    const actionBody = await jsonResponse(actionResponse, `${branch.name} action`);

    assert.equal(actionRequest?.playerAction?.actionType, "give");
    assert.equal(actionRequest?.playerAction?.actorId, "leila");
    assert.equal(actionRequest?.playerAction?.targetId, branch.targetId);
    assert.equal(
      actionRequest?.playerAction?.expectedEventSequence,
      0,
      branch.name + " must send the canonical sequence currently observed by the client",
    );
    assert.deepEqual(actionRequest?.playerAction?.evidenceIds, ["photo_pair"]);

    assert.equal(actionBody.ok, true, `${branch.name} action should be accepted`);
    assert.ok(actionBody.clientActionId, `${branch.name} action should be traceable`);
    assert.equal(actionBody.fallbackUsed, false, `${branch.name} must not use fallback`);
    assert.equal(actionBody.degraded, "none", `${branch.name} must stay on the real gold path`);
    assert.equal(actionBody.eventSequence, 1, `${branch.name} should be the first canonical event`);
    assert.equal(actionBody.snapshot?.runId, runId);
    assert.equal(actionBody.snapshot?.eventSequence, 1);
    assert.equal(actionBody.snapshot?.canonicalState?.phase, "ended");
    assert.equal(actionBody.snapshot?.canonicalState?.endingId, branch.endingId);
    assert.equal(actionBody.outcome?.nextBeat?.transition, "end_scene");
    assert.equal(actionBody.outcome?.nextBeat?.legalEndingId, branch.endingId);

    const persistedResponse = await context.request.get(
      `${BACKEND}/v1/runs/${runId}/snapshot`,
      { timeout: TIMEOUT },
    );
    assert.equal(
      persistedResponse.status(),
      200,
      `${branch.name} persisted snapshot should return HTTP 200`,
    );
    const persistedBody = await persistedResponse.json();
    const persisted = persistedBody?.snapshot;
    assert.equal(persisted?.runId, runId);
    assert.equal(persisted?.eventSequence, 1);
    assert.equal(persisted?.canonicalState?.phase, "ended");
    assert.equal(persisted?.canonicalState?.endingId, branch.endingId);

    const persistedSeeds = (persisted?.causalSeedsActive || []).map(
      (seed) => seed.seedId || seed.id,
    );
    assert.deepEqual(
      exactSorted(persistedSeeds),
      exactSorted(branch.seeds),
      `${branch.name} should persist only its exact causal seed set`,
    );

    const consequence = page.getByTestId("photo-ending-consequence");
    await assert.doesNotReject(
      consequence.waitFor({ state: "visible", timeout: TIMEOUT }),
      `${branch.name} should show the immediate consequence overlay`,
    );
    const consequenceText = (await consequence.innerText()).trim();
    assert.match(
      consequenceText,
      branch.consequencePattern,
      `${branch.name} overlay should explain who carries the photos`,
    );

    return {
      name: branch.name,
      runId,
      endingId: persisted.canonicalState.endingId,
      seeds: exactSorted(persistedSeeds),
      consequenceText,
    };
  } finally {
    await context.close();
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  try {
    const results = [];
    for (const branch of BRANCHES) {
      results.push(await runBranch(browser, branch));
    }

    const [split, keepBoth] = results;
    assert.notEqual(split.runId, keepBoth.runId, "branches must use two fresh runs");
    assert.notEqual(split.endingId, keepBoth.endingId, "branches must persist different endings");
    assert.notDeepEqual(split.seeds, keepBoth.seeds, "branches must persist different causal seeds");
    assert.notEqual(
      split.consequenceText,
      keepBoth.consequenceText,
      "branches must show different immediate consequences",
    );

    console.log(
      JSON.stringify(
        {
          ok: true,
          frontend: FRONTEND,
          backend: BACKEND,
          branches: results,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
