// Extracts visible lead data from a LinkedIn profile or a company website.
function extractLead() {
  const url = window.location.href;
  let data = { name: "", company: "", website: url };

  if (url.includes("linkedin.com/in/")) {
    // LinkedIn personal profile
    const nameEl = document.querySelector("h1");
    if (nameEl) data.name = nameEl.innerText.trim();
    // headline / current company — LinkedIn DOM varies; best-effort
    const headline = document.querySelector(".text-body-medium");
    if (headline) {
      const txt = headline.innerText;
      const at = txt.split(" at ");
      if (at.length > 1) data.company = at[1].trim();
    }
    // try the experience/company anchor
    const compEl = document.querySelector('[aria-label*="Current company"]') ||
                   document.querySelector('button[aria-label*="company"]');
    if (compEl && !data.company) data.company = compEl.innerText.trim();
  } else if (url.includes("linkedin.com/company/")) {
    // LinkedIn company page
    const nameEl = document.querySelector("h1");
    if (nameEl) data.company = nameEl.innerText.trim();
  } else {
    // generic company website — use the page title + domain
    data.company = (document.title || "").split("|")[0].split("-")[0].trim();
    data.website = window.location.origin;
  }
  return data;
}
extractLead();