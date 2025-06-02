import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Last inn bilmerker og modeller fra bilmerker.json
with open("bilmerker.json", "r", encoding="utf-8") as f:
    CAR_DATA = json.load(f)

# Hjelpefunksjon for scraping av FINN-annonser med angitte søkekriterier
def fetch_prices_from_finn(brand, model, year, km, fuel, transmission):
    # Bygg FINN-søk URL basert på parametere (enkelt representert, mer avansert filtrering kan kreve finjustering)
    base_url = "https://www.finn.no/motor/used-cars/search.html?"
    query_params = []
    if brand:
        query_params.append(f"make={brand}")
    if model:
        query_params.append(f"model={model}")
    if year:
        query_params.append(f"year_from={year}&year_to={year}")
    if km:
        query_params.append(f"mileage_to={km}")
    if fuel:
        query_params.append(f"fuel={fuel}")
    if transmission:
        query_params.append(f"transmission={transmission}")
    search_url = base_url + "&".join(query_params)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/113.0.0.0 Safari/537.36"
    }
    prices = []
    try:
        resp = requests.get(search_url, headers=headers, timeout=5)
        resp.raise_for_status()
    except Exception:
        return prices  # Returnerer tom liste ved nettverks-/timeout-feil
    html = resp.text

    # Finn prisene i HTML (bruk enkel parsing ettersom FINN-siden ikke er strukturert for enkel HTML-parsing)
    # Her leter vi etter mønster som '>&nbsp;Pris <strong>123 456</strong>' 
    lines = html.splitlines()
    for line in lines:
        if "Pris" in line and "strong" in line:
            # Forsøk å trekke ut tall fra linjen (fjerner tusenskilletegn og tekst)
            text = line.strip()
            # Eksempel: ">Pris <strong>123 456</strong>"
            start = text.find("<strong>")
            end = text.find("</strong>")
            if start != -1 and end != -1:
                price_str = text[start+8:end]
                price_str = price_str.replace("&nbsp;", "").replace(" ", "")
                if price_str.isdigit():
                    prices.append(int(price_str))
    return prices

@app.route("/models")
def get_models():
    brand = request.args.get("brand")
    if not brand:
        return jsonify({"error": "Angi bilmerke med ?brand="}), 400
    # Normaliser merke-navn for oppslag (store forbokstaver)
    brand_key = brand[0].upper() + brand[1:].lower()
    models = CAR_DATA.get(brand_key)
    if models is None:
        return jsonify({"error": f"Bilmerke '{brand}' finnes ikke"}), 404
    return jsonify({ "brand": brand_key, "models": models })

@app.route("/estimate")
def estimate_price():
    # Hent og valider nødvendige parametere
    brand = request.args.get("brand")
    model = request.args.get("model")
    year = request.args.get("year")
    km = request.args.get("km")  # kilometerstand
    fuel = request.args.get("fuel")
    gearbox = request.args.get("gearbox")
    if not brand or not model or not year or not km or not fuel or not gearbox:
        return jsonify({"error": "Mangler en eller flere parametere: brand, model, year, km, fuel, gearbox"}), 400

    # Gjør et enkelt oppslag mot CAR_DATA for å validere merke/modell
    brand_key = brand[0].upper() + brand[1:].lower()
    if brand_key not in CAR_DATA or model not in CAR_DATA[brand_key]:
        return jsonify({"error": "Ugyldig merke eller modell"}), 404

    # Scrape FINN for priser
    prices = fetch_prices_from_finn(brand_key, model, year, km, fuel, gearbox)
    if not prices:
        # Prøv fallback uten modell (bare merke)
        prices = fetch_prices_from_finn(brand_key, None, year, km, fuel, gearbox)
    if not prices:
        return jsonify({"message": "Ingen priser funnet for angitte kriterier"}), 200

    # Beregn min, maks, median og snitt
    prices.sort()
    count = len(prices)
    minimum = prices[0]
    maximum = prices[-1]
    median = prices[count//2] if count % 2 == 1 else (prices[count//2 - 1] + prices[count//2]) // 2
    average = sum(prices) // count

    return jsonify({
        "brand": brand_key,
        "model": model,
        "year": year,
        "km": km,
        "fuel": fuel,
        "gearbox": gearbox,
        "price_estimate": {
            "min": minimum,
            "max": maximum,
            "median": median,
            "average": average
        }
    })

# For deploy i Render: bruk port fra miljøvariabel eller default 5000
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
