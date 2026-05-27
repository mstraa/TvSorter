initializeTheme();
initializeBrowseStatusFilters();

let progressTimer = null;
let progressVisible = false;

document.addEventListener("submit", (event) => {
  const submitter = event.submitter;
  if (submitter?.dataset?.noProgress === "true") {
    return;
  }
  const action = submitter?.getAttribute("formaction") || event.target.getAttribute("action") || "";
  if (action.includes("/imports")) {
    event.preventDefault();
    startImportJob(event.target, submitter);
    return;
  }
  const label = progressLabelForSubmitter(submitter);
  startDelayedProgress(label);
});

document.addEventListener("change", (event) => {
  const browseCheckbox = event.target.closest('.browse-row input[name="selected"]');
  if (browseCheckbox) {
    browseCheckbox.closest(".browse-row").classList.toggle("selected-row", browseCheckbox.checked);
    return;
  }

  const browseStatusSelect = event.target.closest("[data-browse-status-select]");
  if (browseStatusSelect) {
    updateBrowseStatusRows(browseStatusSelect);
    return;
  }

  const stateFilter = event.target.closest("[data-state-filter] input");
  if (stateFilter) {
    updateStateRows(stateFilter.closest("[data-state-filter]"));
    return;
  }

  const select = event.target.closest(".candidate-select");
  if (!select) {
    return;
  }

  const row = select.closest(".match-row");
  const [provider, providerId, title, year] = select.value.split("|");
  row.querySelector(".provider-input").value = provider || "";
  row.querySelector(".provider-id-input").value = providerId || "";
  row.querySelector(".show-title-input").value = title || "";
  row.querySelector(".show-year-input").value = year || "";
});

const folderDialog = document.getElementById("folder-picker");
const folderPathInput = document.getElementById("folder-picker-path");
const folderList = document.getElementById("folder-picker-list");
const folderRoots = document.getElementById("folder-picker-roots");
const folderError = document.getElementById("folder-picker-error");
let folderPickerTarget = null;
let folderPickerMode = "replace";
let folderPickerParent = null;

document.addEventListener("click", async (event) => {
  const themeButton = event.target.closest("[data-theme-toggle]");
  if (themeButton) {
    toggleTheme();
    return;
  }

  const openButton = event.target.closest("[data-folder-picker]");
  if (openButton) {
    folderPickerTarget = document.getElementById(openButton.dataset.target);
    folderPickerMode = openButton.dataset.mode || "replace";
    const initialPath = initialFolderPath(folderPickerTarget);
    folderDialog.showModal();
    await loadFolder(initialPath);
    return;
  }

  if (event.target.closest("[data-folder-close]")) {
    folderDialog.close();
    return;
  }

  const applyStatusButton = event.target.closest("[data-apply-selected-status]");
  if (applyStatusButton) {
    await applySelectedSourceStatus(applyStatusButton);
    return;
  }

  if (event.target.closest("[data-folder-go]")) {
    await loadFolder(folderPathInput.value);
    return;
  }

  if (event.target.closest("[data-folder-up]")) {
    if (folderPickerParent) {
      await loadFolder(folderPickerParent);
    }
    return;
  }

  if (event.target.closest("[data-folder-choose]")) {
    chooseFolder(folderPathInput.value);
    folderDialog.close();
    return;
  }

  const folderEntry = event.target.closest("[data-folder-path]");
  if (folderEntry) {
    await loadFolder(folderEntry.dataset.folderPath);
    return;
  }

  const browseRow = event.target.closest(".browse-row");
  if (browseRow && !event.target.closest("a, button, input, select, textarea, label")) {
    const checkbox = browseRow.querySelector('input[name="selected"]');
    if (checkbox) {
      checkbox.checked = !checkbox.checked;
      browseRow.classList.toggle("selected-row", checkbox.checked);
    }
  }
});

folderPathInput?.addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    await loadFolder(folderPathInput.value);
  }
});

async function loadFolder(path) {
  setFolderError("");
  folderList.replaceChildren();
  startDelayedProgress("Opening folder...");
  try {
    const response = await fetch(`/api/folders?path=${encodeURIComponent(path || "/")}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      setFolderError(payload.detail || "Could not open folder");
      return;
    }

    const payload = await response.json();
    folderPathInput.value = payload.path;
    folderPickerParent = payload.parent;
    renderFolderRoots(payload.roots);
    renderFolderList(payload.folders);
  } finally {
    stopDelayedProgress();
  }
}

function renderFolderRoots(roots) {
  folderRoots.replaceChildren();
  for (const root of roots) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "folder-root-button";
    button.dataset.folderPath = root;
    button.textContent = root;
    folderRoots.append(button);
  }
}

function renderFolderList(folders) {
  folderList.replaceChildren();
  if (!folders.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No folders found.";
    folderList.append(empty);
    return;
  }

  for (const folder of folders) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "folder-entry";
    button.dataset.folderPath = folder.path;
    button.innerHTML = `<span>${escapeHtml(folder.name)}</span><span class="muted">${escapeHtml(folder.path)}</span>`;
    folderList.append(button);
  }
}

function chooseFolder(path) {
  if (!folderPickerTarget) {
    return;
  }

  if (folderPickerMode === "append") {
    const existing = folderPickerTarget.value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (!existing.includes(path)) {
      existing.push(path);
    }
    folderPickerTarget.value = existing.join("\n");
    return;
  }

  folderPickerTarget.value = path;
}

function initialFolderPath(target) {
  if (!target) {
    return "/";
  }
  if (target.tagName === "TEXTAREA") {
    const firstLine = target.value.split("\n").map((line) => line.trim()).find(Boolean);
    return firstLine || "/";
  }
  return target.value.trim() || "/";
}

function setFolderError(message) {
  folderError.textContent = message;
  folderError.hidden = !message;
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

function updateStateRows(filter) {
  const enabledStates = new Set(
    Array.from(filter.querySelectorAll("input:checked")).map((input) => input.value),
  );
  document.querySelectorAll(".state-row").forEach((row) => {
    row.hidden = !enabledStates.has(row.dataset.state);
  });
}

function initializeBrowseStatusFilters() {
  document.querySelectorAll("[data-browse-status-select]").forEach((select) => updateBrowseStatusRows(select));
}

function updateBrowseStatusRows(select) {
  const selectedState = select.value;
  document.querySelectorAll(".browse-row").forEach((row) => {
    row.hidden = selectedState !== "all" && row.dataset.browseStatus !== selectedState;
  });
}

async function applySelectedSourceStatus(button) {
  const form = button.closest("form");
  const selected = Array.from(form.querySelectorAll('input[name="selected"]:checked')).map((input) => input.value);
  if (!selected.length) {
    alert("Select one or more files or folders first.");
    return;
  }
  const formData = new FormData();
  formData.set("root_id", form.querySelector('input[name="root_id"]').value);
  formData.set("status", form.querySelector("[data-selected-status]").value);
  for (const relativePath of selected) {
    formData.append("selected", relativePath);
  }
  button.disabled = true;
  startDelayedProgress("Updating status...");
  try {
    const response = await fetch("/api/source-status", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      alert(payload.detail || "Could not update status.");
      return;
    }
    window.location.reload();
  } finally {
    button.disabled = false;
    stopDelayedProgress();
  }
}

async function startImportJob(form, submitter) {
  const formData = new FormData(form);
  if (submitter) {
    submitter.disabled = true;
  }
  startDelayedProgress("Starting import...", true);
  try {
    const response = await fetch("/api/import-jobs", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      alert("Could not start import.");
      stopDelayedProgress();
      return;
    }
    const job = await response.json();
    updateProgress(job);
    await pollImportJob(job.id);
  } finally {
    if (submitter) {
      submitter.disabled = false;
    }
  }
}

async function pollImportJob(jobId) {
  while (true) {
    const response = await fetch(`/api/import-jobs/${encodeURIComponent(jobId)}`);
    if (!response.ok) {
      stopDelayedProgress();
      alert("Could not read import progress.");
      return;
    }
    const job = await response.json();
    updateProgress(job);
    if (job.state === "done") {
      stopDelayedProgress();
      window.location.href = `/import-jobs/${encodeURIComponent(jobId)}/results`;
      return;
    }
    if (job.state === "failed") {
      stopDelayedProgress();
      alert(job.error || "Import failed.");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
}

function initializeTheme() {
  const savedTheme = localStorage.getItem("tvsorter-theme");
  const preferredTheme = window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  setTheme(savedTheme || preferredTheme);
}

function toggleTheme() {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("tvsorter-theme", theme);
  const button = document.querySelector("[data-theme-toggle]");
  if (button) {
    button.textContent = theme === "dark" ? "Light" : "Dark";
    button.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`);
  }
}

function progressLabelForSubmitter(submitter) {
  if (!submitter) {
    return "Working...";
  }
  const action = submitter.getAttribute("formaction") || submitter.form?.getAttribute("action") || "";
  const label = submitter.textContent.trim();
  if (action.includes("/imports") || label === "Import") {
    return "Importing...";
  }
  if (action.includes("/preview") || label === "Preview") {
    return "Building preview...";
  }
  if (action.includes("/match") || label === "Match Selected") {
    return "Matching metadata...";
  }
  return "Working...";
}

function startDelayedProgress(label, determinate = false) {
  stopDelayedProgress();
  setProgressState({ percent: determinate ? 0 : null, label, currentItem: "", detail: "" });
  progressTimer = window.setTimeout(() => {
    const overlay = document.querySelector("[data-progress-overlay]");
    if (!overlay) {
      return;
    }
    overlay.hidden = false;
    progressVisible = true;
  }, 2000);
}

function stopDelayedProgress() {
  if (progressTimer) {
    window.clearTimeout(progressTimer);
    progressTimer = null;
  }
  if (progressVisible) {
    const overlay = document.querySelector("[data-progress-overlay]");
    if (overlay) {
      overlay.hidden = true;
    }
    progressVisible = false;
  }
}

window.startDelayedProgress = startDelayedProgress;
window.stopDelayedProgress = stopDelayedProgress;
window.updateProgress = updateProgress;

function updateProgress(job) {
  const itemPosition = job.current_item_index && job.total_items ? `item ${job.current_item_index} of ${job.total_items}` : "";
  const label = itemPosition ? `Importing ${itemPosition}` : "Importing...";
  setProgressState({
    percent: job.percent,
    label,
    currentItem: job.current_item || "",
    detail: progressDetail(job),
  });
}

function setProgressState({ percent, label, currentItem, detail }) {
  const overlay = document.querySelector("[data-progress-overlay]");
  const labelElement = document.querySelector("[data-progress-label]");
  const itemElement = document.querySelector("[data-progress-item]");
  const percentElement = document.querySelector("[data-progress-percent]");
  const detailElement = document.querySelector("[data-progress-detail]");
  const bar = document.querySelector("[data-progress-bar]");
  if (!overlay || !labelElement || !itemElement || !percentElement || !detailElement || !bar) {
    return;
  }
  labelElement.textContent = label;
  itemElement.textContent = currentItem || "";
  detailElement.textContent = detail || "";
  if (typeof percent === "number") {
    overlay.dataset.progressMode = "determinate";
    percentElement.textContent = `${Math.max(0, Math.min(100, percent))}%`;
    bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  } else {
    overlay.dataset.progressMode = "indeterminate";
    percentElement.textContent = "";
    bar.style.width = "";
  }
}

function progressDetail(job) {
  const parts = [];
  if (typeof job.completed_items === "number" && typeof job.total_items === "number") {
    parts.push(`${job.completed_items}/${job.total_items} items done`);
  }
  if (job.current_action === "copy" && job.current_item_total > 0) {
    parts.push(
      `${job.current_item_percent}% of current file (${formatBytes(job.current_item_bytes)} / ${formatBytes(job.current_item_total)})`,
    );
  } else if (job.current_action) {
    parts.push(`${job.current_action} in progress`);
  }
  if (job.current_action === "copy" && typeof job.completed === "number" && typeof job.total === "number" && job.total > 0) {
    parts.push(`${formatBytes(job.completed)} / ${formatBytes(job.total)} total`);
  }
  return parts.join(" - ");
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 o";
  }
  const units = ["o", "Ko", "Mo", "Go", "To"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / (1024 ** exponent);
  const precision = exponent <= 2 ? 0 : 2;
  let formatted = value.toFixed(precision);
  if (formatted.includes(".")) {
    formatted = formatted.replace(/0+$/, "").replace(/\.$/, "");
  }
  formatted = formatted.replace(".", ",");
  return `${formatted} ${units[exponent]}`;
}
