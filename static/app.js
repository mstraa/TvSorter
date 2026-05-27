document.addEventListener("change", (event) => {
  const browseStatusFilter = event.target.closest("[data-browse-status-filter] input");
  if (browseStatusFilter) {
    updateBrowseStatusRows(browseStatusFilter.closest("[data-browse-status-filter]"));
    return;
  }

  const manualStatusSelect = event.target.closest(".manual-status-select");
  if (manualStatusSelect) {
    updateManualSourceStatus(manualStatusSelect);
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

  const onlyStatusButton = event.target.closest("[data-browse-filter-only]");
  if (onlyStatusButton) {
    const filter = onlyStatusButton.closest("[data-browse-status-filter]");
    setBrowseStatusFilter(filter, onlyStatusButton.dataset.browseFilterOnly);
    return;
  }

  const allStatusButton = event.target.closest("[data-browse-filter-all]");
  if (allStatusButton) {
    const filter = allStatusButton.closest("[data-browse-status-filter]");
    setBrowseStatusFilter(filter, null);
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

function updateBrowseStatusRows(filter) {
  const enabledStates = new Set(
    Array.from(filter.querySelectorAll("input:checked")).map((input) => input.value),
  );
  document.querySelectorAll(".browse-row").forEach((row) => {
    const isFolder = row.dataset.browseFolder === "1";
    row.hidden = !isFolder && !enabledStates.has(row.dataset.browseStatus);
  });
}

function setBrowseStatusFilter(filter, onlyStatus) {
  filter.querySelectorAll("input").forEach((input) => {
    input.checked = onlyStatus ? input.value === onlyStatus : true;
  });
  updateBrowseStatusRows(filter);
}

async function updateManualSourceStatus(select) {
  const formData = new FormData();
  formData.set("source_path", select.dataset.sourcePath);
  formData.set("status", select.value);
  select.disabled = true;
  const response = await fetch("/api/source-status", {
    method: "POST",
    body: formData,
  });
  select.disabled = false;
  if (!response.ok) {
    alert("Could not update status.");
    return;
  }
  window.location.reload();
}
