const token = window.SESSION_TOKEN;
const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-Session-Token": token },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

api("/api/tenant")
  .then((d) => {
    $("tenant").textContent = `Target tenant: ${d.tenant}`;
    if (d.tenant.includes("[PRODUCTION]")) $("tenant").classList.add("production");
  })
  .catch((e) => { $("tenant").textContent = `Could not identify tenant: ${e.message}`; });

$("inspect").addEventListener("click", async () => {
  try {
    const d = await api("/api/inspect", { archive: $("archive").value });
    renderSelections(d.selections);
    $("selection").hidden = false;
  } catch (e) { show({ error: e.message }); }
});

function renderSelections(selections) {
  const byGroup = {};
  for (const s of selections) (byGroup[s.group] ||= []).push(s);
  $("groups").innerHTML = Object.entries(byGroup).map(([group, rows]) => `
    <fieldset>
      <legend>${group}</legend>
      ${rows.map((r) => `
        <label class="${r.writable ? "" : "readonly"}">
          <input type="checkbox" value="${r.key}" ${r.writable ? "" : "disabled"}>
          ${r.label} <span class="count">${r.count}</span>
          ${r.writable ? "" : '<span class="note">no write API - export reference only</span>'}
        </label>`).join("")}
    </fieldset>`).join("");
}

$("run").addEventListener("click", async () => {
  const keys = [...document.querySelectorAll("#groups input:checked")].map((i) => i.value);
  if (!keys.length) return show({ error: "Nothing selected." });
  try {
    show(await api("/api/import", {
      archive: $("archive").value,
      keys,
      onConflict: $("conflict").value,
      confirm: $("confirm").checked,
    }));
  } catch (e) { show({ error: e.message }); }
});

function show(obj) {
  $("output").hidden = false;
  $("output").textContent = JSON.stringify(obj, null, 2);
}
