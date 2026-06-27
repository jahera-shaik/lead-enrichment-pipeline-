const API = "http://127.0.0.1:8000";

// On open, run a script in the current page to read lead data from the DOM
chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
  const tab = tabs[0];
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const url = window.location.href;
        let data = { name: "", company: "", website: url };

        if (url.includes("linkedin.com/in/")) {
          // ---- LinkedIn personal profile ----
          const n = document.querySelector("h1");
          if (n) data.name = n.innerText.trim();

          let comp = "";
          // 1) headline often reads "Role at Company"
          const headline = document.querySelector(".text-body-medium.break-words")
                        || document.querySelector(".text-body-medium");
          if (headline && headline.innerText.includes(" at ")) {
            comp = headline.innerText.split(" at ").pop().trim();
          }
          // 2) current-company button aria-label
          if (!comp) {
            const btn = document.querySelector('button[aria-label*=" at "]')
                     || document.querySelector('[data-field="experience_company_logo"]');
            if (btn) {
              const al = btn.getAttribute("aria-label") || btn.innerText || "";
              if (al.includes(" at ")) comp = al.split(" at ").pop().trim();
            }
          }
          // 3) any company link in the top card
          if (!comp) {
            const link = document.querySelector('a[href*="/company/"]');
            if (link) comp = link.innerText.trim();
          }
          data.company = comp;

        } else if (url.includes("linkedin.com/company/")) {
          // ---- LinkedIn company page ----
          const n = document.querySelector("h1");
          if (n) data.company = n.innerText.trim();

        } else {
          // ---- generic company website ----
          data.company = (document.title || "").split("|")[0].split("-")[0].trim();
          data.website = window.location.origin;
        }
        return data;
      },
    });

    const d = results[0].result;
    document.getElementById("name").value = d.name || "";
    document.getElementById("company").value = d.company || "";
    document.getElementById("website").value = d.website || "";
  } catch (e) {
    document.getElementById("status").textContent =
      "Couldn't read page. Type the details manually below.";
  }
});

// Enrich button → call the backend
document.getElementById("enrich").addEventListener("click", async () => {
  const btn = document.getElementById("enrich");
  const status = document.getElementById("status");
  const result = document.getElementById("result");
  btn.disabled = true;
  status.innerHTML = '<span class="spin"></span> Enriching… (~30s)';
  result.style.display = "none";

  const body = {
    name: document.getElementById("name").value,
    company: document.getElementById("company").value,
    website: document.getElementById("website").value,
    email: "",
  };

  try {
    const r = await fetch(API + "/enrich", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!r.ok) {
      status.textContent = "Error: " + (d.detail || "failed");
      btn.disabled = false;
      return;
    }
    status.textContent = "";
    result.style.display = "block";
    result.innerHTML = `
      <div class="metric"><span>ICP Score</span><b>${d.icp_score}</b></div>
      <div class="metric"><span>Combined</span><b>${d.combined_score}</b></div>
      <div class="metric"><span>Qualified</span><b class="${d.qualified ? 'qual-yes' : 'qual-no'}">${d.qualified ? 'Yes' : 'No'}</b></div>
      ${d.top_signal ? `<div class="badge">${d.top_signal}</div>` : '<div class="status">No buying signal detected</div>'}
      <div class="status">✓ Saved to dashboard</div>`;
  } catch (e) {
    status.textContent = "Could not reach backend. Is the server running?";
  }
  btn.disabled = false;
});