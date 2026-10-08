// Reads resolve_input.json (items with a Google News redirect link),
// resolves each to its real publisher URL via a real browser navigation
// (curl/httpx can't do this — the redirect only fires from client-side JS),
// and writes the enriched list to resolve_output.json.
const fs = require("fs");
const { chromium } = require("playwright");

async function resolveOne(browser, googleLink) {
  const page = await browser.newPage();
  try {
    await page.goto(googleLink, { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForURL((u) => !u.href.includes("/rss/articles/"), { timeout: 15000 });
    return page.url();
  } catch (e) {
    return null;
  } finally {
    await page.close();
  }
}

(async () => {
  const items = JSON.parse(fs.readFileSync("resolve_input.json", "utf-8"));
  const browser = await chromium.launch();
  const results = new Array(items.length);
  // Each lookup is mostly waiting on the redirect (up to 30s on a miss), so a
  // few tabs at once cut the run time several-fold.
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      const realUrl = await resolveOne(browser, items[i].google_link);
      results[i] = { ...items[i], source_url: realUrl || items[i].google_link };
      console.log(`${realUrl ? "resolved" : "FAILED (kept google link)"}: ${items[i].title.slice(0, 50)}`);
    }
  };
  await Promise.all(Array.from({ length: 5 }, worker));
  await browser.close();
  fs.writeFileSync("resolve_output.json", JSON.stringify(results));
})();
