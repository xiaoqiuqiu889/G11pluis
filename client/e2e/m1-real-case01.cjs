/**
 * M1 acceptance canary: case 01, real client -> real FastAPI.
 *
 * Preconditions (from the repository root):
 *   1. Double-click `Demo-01.cmd` (VITE_USE_MOCK=false). If it selects a port
 *      other than 5173, set G1N_FRONTEND_URL to the printed Demo URL origin.
 *   2. Run: node client/e2e/m1-real-case01.cjs
 *
 * This deliberately does not intercept or mock any /v1 request.  A pass proves
 * that the browser created a server-owned run, entered photo_lab_2008, sent the
 * Give action with the causal evidence, received a persisted server turn, and
 * rendered the authoritative shared_secret ending.
 */

const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const FRONTEND = process.env.G1N_FRONTEND_URL || "http://127.0.0.1:5173";
const BACKEND = process.env.G1N_BACKEND_URL || "http://127.0.0.1:8000";
const SCENE_ID = "photo_lab_2008";
const CASE_SLUG = "case_01_revolution_street";
const TIMEOUT_MS = 20_000;

function apiPath(response, suffix) {
  try {
    return new URL(response.url()).pathname === suffix;
  } catch {
    return false;
  }
}

async function responseJson(response, label) {
  if (!response.ok()) {
    const body = await response.text();
    assert.fail(`${label} returned HTTP ${response.status()}: ${body}`);
  }
  const body = await response.json();
  return body;
}

async function requireRealStack() {
  let health;
  try {
    health = await fetch(`${BACKEND}/health`, {
      signal: AbortSignal.timeout(5_000),
    });
  } catch (error) {
    throw new Error(
      `FastAPI is not reachable at ${BACKEND}. Start the real stack with ` +
        `\`Demo-01.cmd\` before this test. Original error: ${error.message}`,
    );
  }
  assert.equal(health.ok, true, `FastAPI /health returned ${health.status}`);

  let frontend;
  try {
    frontend = await fetch(`${FRONTEND}/scene/${SCENE_ID}`, {
      signal: AbortSignal.timeout(5_000),
    });
  } catch (error) {
    throw new Error(
      `Vite is not reachable at ${FRONTEND}. Start the real stack with ` +
        `\`Demo-01.cmd\` before this test. Original error: ${error.message}`,
    );
  }
  assert.equal(frontend.ok, true, `Vite scene route returned ${frontend.status}`);
}

async function main() {
  await requireRealStack();

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: "zh-CN",
  });
  const page = await context.newPage();

  const pageErrors = [];
  const fallbackSignals = [];
  const relevantResponses = [];

  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    const text = message.text();
    if (/synthetic|run not found|\b404\b|\bL4\b/i.test(text)) {
      fallbackSignals.push(`${message.type()}: ${text}`);
    }
  });
  page.on("response", (response) => {
    const pathname = new URL(response.url()).pathname;
    if (pathname.startsWith("/v1/runs")) {
      relevantResponses.push({
        method: response.request().method(),
        pathname,
        status: response.status(),
      });
    }
  });

  try {
    // Register both waiters before navigation: enter follows create immediately.
    const createResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        apiPath(response, "/v1/runs"),
      { timeout: TIMEOUT_MS },
    );
    const enterResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/v1\/runs\/[^/]+\/scenes\/photo_lab_2008\/enter$/.test(
          new URL(response.url()).pathname,
        ),
      { timeout: TIMEOUT_MS },
    );

    await page.goto(`${FRONTEND}/scene/${SCENE_ID}`, {
      waitUntil: "domcontentloaded",
      timeout: TIMEOUT_MS,
    });

    const createResponse = await createResponsePromise;
    const createBody = await responseJson(createResponse, "POST /v1/runs");
    assert.equal(createBody.ok, true, "createRun response must declare ok=true");
    assert.equal(
      createResponse.request().postDataJSON().caseSlug,
      CASE_SLUG,
      "the browser must create the first-case run",
    );
    assert.equal(
      createResponse.request().postDataJSON().startSceneId,
      SCENE_ID,
      "the server run must start in photo_lab_2008",
    );
    const runId = createBody.run && createBody.run.runId;
    assert.match(
      runId || "",
      /^[0-9a-f]{8}-[0-9a-f-]{27}$/i,
      "createRun must return a server-owned UUID",
    );

    const enterResponse = await enterResponsePromise;
    const enterBody = await responseJson(
      enterResponse,
      "POST /v1/runs/:runId/scenes/photo_lab_2008/enter",
    );
    assert.equal(enterBody.ok, true, "enterScene response must declare ok=true");
    assert.equal(enterBody.runId, runId, "enterScene must use the created runId");
    assert.equal(enterBody.sceneId, SCENE_ID);
    assert.equal(
      new URL(enterResponse.url()).pathname,
      `/v1/runs/${runId}/scenes/${SCENE_ID}/enter`,
      "the browser must enter the scene on the same server run",
    );

    // The primary contextual choice submits immediately; arm the waiter first.
    const actionResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/v1/runs/${runId}/actions`,
      { timeout: TIMEOUT_MS },
    );
    const splitChoice = page.getByTestId("photo-choice-split");
    await splitChoice.waitFor({ state: "visible", timeout: TIMEOUT_MS });
    await splitChoice.click();

    const actionResponse = await actionResponsePromise;
    const actionRequest = actionResponse.request();
    const actionRequestBody = actionRequest.postDataJSON();
    assert.equal(actionRequestBody.runId, runId);
    assert.equal(actionRequestBody.sceneId, SCENE_ID);
    assert.equal(actionRequestBody.playerAction.actionType, "give");
    assert.equal(actionRequestBody.playerAction.actorId, "leila");
    assert.equal(actionRequestBody.playerAction.targetId, "arash");
    assert.equal(
      actionRequestBody.playerAction.expectedEventSequence,
      0,
      "the first action must send the canonical sequence currently observed by the client",
    );
    assert.deepEqual(
      actionRequestBody.playerAction.evidenceIds,
      ["photo_pair"],
      "Give must carry the photo_pair causal evidence",
    );

    const actionBody = await responseJson(
      actionResponse,
      "POST /v1/runs/:runId/actions",
    );
    assert.equal(actionBody.ok, true);
    assert.equal(actionBody.clientActionId, actionRequestBody.clientActionId);
    assert.equal(
      actionBody.fallbackUsed,
      false,
      "M1 must not pass through a synthetic/fallback turn",
    );
    assert.notEqual(actionBody.degraded, "L4", "M1 must not silently degrade to L4");
    assert.ok(actionBody.eventSequence >= 1, "the server must persist the action event");
    assert.equal(actionBody.snapshot.runId, runId);
    assert.equal(actionBody.snapshot.eventSequence, actionBody.eventSequence);
    assert.equal(actionBody.snapshot.canonicalState.phase, "ended");
    assert.equal(actionBody.snapshot.canonicalState.endingId, "shared_secret");
    assert.equal(actionBody.outcome.nextBeat.transition, "end_scene");
    assert.equal(actionBody.outcome.nextBeat.legalEndingId, "shared_secret");
    assert.equal(
      JSON.stringify(actionBody).toLowerCase().includes("synthetic"),
      false,
      "the real action response must not contain a synthetic-success marker",
    );

    // Re-read from the API so the test cannot pass on client-only optimistic state.
    const persistedResponse = await context.request.get(
      `${BACKEND}/v1/runs/${runId}/snapshot`,
      { timeout: TIMEOUT_MS },
    );
    assert.equal(
      persistedResponse.ok(),
      true,
      `persisted snapshot returned HTTP ${persistedResponse.status()}`,
    );
    const persistedBody = await persistedResponse.json();
    const persisted = persistedBody.snapshot;
    assert.equal(persisted.runId, runId);
    assert.equal(persisted.eventSequence, actionBody.eventSequence);
    assert.equal(persisted.canonicalState.phase, "ended");
    assert.equal(persisted.canonicalState.endingId, "shared_secret");
    const seedIds = new Set(persisted.causalSeedsActive.map((seed) => seed.seedId || seed.id));
    assert.deepEqual(
      ["photo_in_pocket", "photo_in_book"].filter((id) => !seedIds.has(id)),
      [],
      "the persisted snapshot must retain both photo causal seeds",
    );

    // Finally prove that applyServerTurn rendered the authoritative consequence.
    const endingConsequence = page.getByTestId("photo-ending-consequence");
    await endingConsequence.waitFor({ state: "visible", timeout: TIMEOUT_MS });
    const endingText = await endingConsequence.innerText();
    assert.match(endingText, /shared_secret/, "the overlay must expose the authoritative ending");
    for (const expectedText of ["一张", "阿拉什", "诗集"]) {
      assert.equal(
        endingText.includes(expectedText),
        true,
        `the split-photo consequence must mention ${expectedText}`,
      );
    }

    assert.deepEqual(pageErrors, [], `unexpected page errors: ${pageErrors.join(" | ")}`);
    assert.deepEqual(
      fallbackSignals,
      [],
      `fallback/synthetic signals reached the browser: ${fallbackSignals.join(" | ")}`,
    );

    console.log(
      JSON.stringify(
        {
          ok: true,
          runId,
          eventSequence: actionBody.eventSequence,
          endingId: persisted.canonicalState.endingId,
          relevantResponses,
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
  console.error("M1 real case 01 failed:", error);
  process.exitCode = 1;
});
