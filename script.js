document.getElementById("brandSelect").addEventListener("change", function() {
    const brand = this.value;
    const modelSelect = document.getElementById("modelSelect");
    modelSelect.innerHTML = "<option disabled selected>Henter modeller...</option>";
    fetch("/models?brand=" + encodeURIComponent(brand))
      .then(res => res.json())
      .then(data => {
        modelSelect.innerHTML = "";
        if (data.models && data.models.length > 0) {
          modelSelect.innerHTML = "<option disabled selected>Velg modell</option>";
          data.models.forEach(mod => {
            const opt = document.createElement("option");
            opt.value = mod.value;
            opt.textContent = mod.name;
            modelSelect.appendChild(opt);
          });
          modelSelect.disabled = false;
        } else {
          modelSelect.innerHTML = "<option disabled selected>Ingen modeller</option>";
          modelSelect.disabled = true;
        }
      })
      .catch(err => {
        modelSelect.innerHTML = "<option disabled selected>Kunne ikke hente</option>";
        modelSelect.disabled = true;
        console.error("Error fetching models:", err);
      });
  });
  