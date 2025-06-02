import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template, jsonify
import json

app = Flask(__name__)

# In-memory caches for data
brand_code_map = {}   # Kartlegging av bilmerke til FINN-kode
region_value_map = {} # Kartlegging av regionnavn til FINN-lokasjonsverdi
model_cache = {}      # Cache for modeller per bilmerke
results_cache = {}    # Cache for prisresultater per søk
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

def fetch_initial_data():
    """Henter liste over bilmerker og områder fra FINN.no ved oppstart."""
    try:
        sess = requests.Session()
        # Gjør et kall til FINN for å få nødvendige cookies
        sess.get("https://www.finn.no/", headers={"User-Agent": USER_AGENT})
        # Hent FINN bruktbilsøk (alle merker) som JSON via HTML
        resp = sess.get("https://www.finn.no/mobility/search/car",
                        params={"registration_class": "1"},  # 1 = bruktbil
                        headers={"User-Agent": USER_AGENT})
        soup = BeautifulSoup(resp.text, "html.parser")
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script:
            return
        data = json.loads(script.string)
        # Bygg opp brand_code_map fra fasetter (aggregations)
        make_facets = data["props"]["pageProps"]["aggregations"].get("make", [])
        for entry in make_facets:
            name = entry.get("displayName")
            val = entry.get("value") or entry.get("code")
            if name and val:
                # FINN oppgir merkeverdi som f.eks. "0.8078" (0.nnnn)
                if isinstance(val, str) and val.startswith("0."):
                    code_str = val.split(".", 1)[1]
                    try:
                        code = int(code_str)
                    except:
                        code = code_str
                else:
                    code = int(val) if isinstance(val, str) and val.isdigit() else val
                brand_code_map[name] = code
        # Bygg opp region_value_map
        loc_facets = data["props"]["pageProps"]["aggregations"].get("location", [])
        for entry in loc_facets:
            name = entry.get("displayName")
            val = entry.get("value")
            if name and val:
                region_value_map[name] = val
    except Exception as e:
        print("Init data error:", e)

def fetch_models_for_brand(brand_name):
    """Henter alle modeller for et gitt bilmerke fra FINN (bruker cache for gjentatte kall)."""
    if brand_name not in brand_code_map:
        return []
    brand_code = brand_code_map[brand_name]
    if brand_code in model_cache:
        return model_cache[brand_code]
    try:
        sess = requests.Session()
        sess.get("https://www.finn.no/", headers={"User-Agent": USER_AGENT})
        # Henter søkeside filtrert på bilmerke for å finne modell-fasetter
        resp = sess.get("https://www.finn.no/mobility/search/car",
                        params={"make": f"0.{brand_code}", "registration_class": "1"},
                        headers={"User-Agent": USER_AGENT})
        soup = BeautifulSoup(resp.text, "html.parser")
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        data = json.loads(script.string)
        model_facets = data["props"]["pageProps"]["aggregations"].get("model", [])
        models = []
        for entry in model_facets:
            mname = entry.get("displayName")
            mval = entry.get("value") or entry.get("code")
            if mname and mval:
                if entry.get("value"):
                    # 'value' er fullstendig søkeverdi som kan brukes direkte
                    models.append((mname, mval))
                else:
                    # Hvis kun kode, kombiner med brand_code til komplett verdi
                    try:
                        mcode = str(int(mval))
                    except:
                        mcode = str(mval)
                    models.append((mname, f"1.{brand_code}.{mcode}"))
        models.sort(key=lambda x: x[0])
        model_cache[brand_code] = models
        return models
    except Exception as e:
        print(f"Model fetch error for {brand_name}:", e)
        return []

def fetch_prices_for_query(params):
    """Henter priser fra FINN for annonser som matcher parametrene. Bruker cache for ytelse."""
    key = tuple(sorted(params.items()))
    if key in results_cache:
        return results_cache[key]
    try:
        sess = requests.Session()
        sess.get("https://www.finn.no/", headers={"User-Agent": USER_AGENT})
        resp = sess.get("https://www.finn.no/mobility/search/car", params=params,
                        headers={"User-Agent": USER_AGENT})
        soup = BeautifulSoup(resp.text, "html.parser")
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        data = json.loads(script.string)
        docs = data["props"]["pageProps"]["search"].get("docs", [])
        prices = []
        headings = []
        for ad in docs:
            price_val = None
            if "price" in ad:
                price_val = ad["price"]
            elif "prices" in ad:
                price_info = ad["prices"]
                price_val = price_info.get("amount") or price_info.get("price") or price_info.get("value")
            # Konverter pris til tall (fjern kr/ mellomrom)
            if isinstance(price_val, str):
                try:
                    price_val = int(price_val.replace(" ", "").replace("kr", "").replace(",", "").strip())
                except:
                    price_val = None
            if price_val:
                prices.append(price_val)
                title = (ad.get("heading") or ad.get("title") or "").lower()
                headings.append(title)
        results_cache[key] = (prices, headings)
        return results_cache[key]
    except Exception as e:
        print("Price fetch error:", e)
        return ([], [])

@app.route("/")
def index():
    # Første gang initialiserer vi merke- og regionlister
    if not brand_code_map or not region_value_map:
        fetch_initial_data()
    brands = sorted(brand_code_map.keys())
    regions = sorted(region_value_map.keys())
    if "Utlandet" in regions:
        regions.remove("Utlandet")
        regions.append("Utlandet")
    # Les inndata fra forespørsel (skjemafeltene)
    brand = request.args.get("brand")
    model_val = request.args.get("model")
    year = request.args.get("year")
    km = request.args.get("km")
    trim = request.args.get("trim")
    fuel = request.args.get("fuel")
    gear = request.args.get("gear")
    location = request.args.get("location")
    result_data = None
    message = None
    if brand and model_val and year and km and fuel and gear:
        # Bygg parametre for FINN-søk
        params = {"registration_class": "1"}  # bruktbil
        if model_val and model_val.startswith("1."):
            params["model"] = model_val
        elif brand:
            code = brand_code_map.get(brand)
            if code:
                params["make"] = f"0.{code}"
        try:
            year_int = int(year)
            params["year_from"] = year_int
            params["year_to"] = year_int
        except:
            pass
        try:
            km_val = int(km)
            params["mileage_from"] = max(0, int(km_val * 0.8))
            params["mileage_to"] = int(km_val * 1.2)
        except:
            pass
        if fuel:
            try:
                params["fuel"] = int(fuel)
            except:
                pass
        if gear:
            try:
                params["transmission"] = int(gear)
            except:
                pass
        if location and location != "Alle":
            loc_val = region_value_map.get(location)
            if loc_val:
                params["location"] = loc_val
        prices, headings = fetch_prices_for_query(params)
        if trim:
            trim_low = trim.strip().lower()
            if trim_low:
                filtered_prices = [price for price, title in zip(prices, headings) if trim_low in title]
                if filtered_prices:
                    prices = filtered_prices
                else:
                    message = f"Ingen annonser funnet med utstyrsnivå \"{trim}\". Viser alle matchende annonser."
        if prices:
            prices.sort()
            n = len(prices)
            avg_price = sum(prices) / n
            if n % 2 == 0:
                median_price = (prices[n//2 - 1] + prices[n//2]) / 2
            else:
                median_price = prices[n//2]
            result_data = {
                "count": n,
                "min": min(prices),
                "max": max(prices),
                "median": int(round(median_price)),
                "average": int(round(avg_price))
            }
        else:
            message = "Fant ingen matching annonser med de valgte kriteriene."
    return render_template("index.html",
                           brands=brands,
                           regions=regions,
                           result=result_data,
                           message=message,
                           form_data=request.args)

@app.route("/models")
def models_endpoint():
    brand_name = request.args.get("brand")
    if not brand_name:
        return jsonify({"models": []})
    models_list = fetch_models_for_brand(brand_name)
    model_dicts = [{"name": m[0], "value": m[1]} for m in models_list]
    return jsonify({"models": model_dicts})

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Bruk Render sin PORT
    app.run(host="0.0.0.0", port=port)
