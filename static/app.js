document.addEventListener("change", (event) => {
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

