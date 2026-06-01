"""
Servidor Flask + Playwright
Endpoint: GET /scrape?url=https://tutiendabancor.com/producto.pp
Retorna JSON: { titulo, sku, precio, stock }
"""

import asyncio
import json
import random
import re
import os
from flask import Flask, request, jsonify
from playwright.async_api import async_playwright

app = Flask(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

async def scrape(url: str) -> dict:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
            ],
        )

        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="es-AR",
            timezone_id="America/Argentina/Cordoba",
            extra_http_headers={
                "Accept-Language":  "es-AR,es;q=0.9,en-US;q=0.8",
                "Accept":           "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer":          "https://www.google.com/",
            },
        )

        # Stealth: ocultar webdriver
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['es-AR', 'es', 'en'] });
            window.chrome = { runtime: {} };
        """)

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(2, 4))

        # Extraer datos via JSON-LD (Magento 2 siempre lo incluye)
        data = await page.evaluate("""
            () => {
                // 1. JSON-LD
                const scripts = [...document.querySelectorAll('script[type="application/ld+json"]')];
                for (const s of scripts) {
                    try {
                        const obj = JSON.parse(s.textContent);
                        const items = Array.isArray(obj) ? obj : [obj];
                        const prod = items.find(o => o && o['@type'] === 'Product');
                        if (prod) {
                            const of = prod.offers || {};
                            return {
                                titulo: prod.name || '',
                                sku:    prod.sku  || '',
                                precio: String(of.price || of.lowPrice || ''),
                                stock:  (of.availability || '').toLowerCase().includes('instock') ? 'En stock' : 'Sin stock',
                                metodo: 'json-ld'
                            };
                        }
                    } catch(e) {}
                }

                // 2. Fallback meta tags
                const titulo = (document.querySelector('h1.page-title span.base') || {}).innerText
                            || document.querySelector('meta[property="og:title"]')?.content || '';
                const sku    = document.querySelector('[itemprop="sku"]')?.innerText || '';
                const precio = document.querySelector('[itemprop="price"]')?.getAttribute('content')
                            || document.querySelector('[data-price-type="finalPrice"] .price')?.innerText || '';
                const inStock  = document.querySelector('.stock.available');
                const outStock = document.querySelector('.stock.unavailable');
                const stock = inStock ? 'En stock' : outStock ? 'Sin stock' : 'Desconocido';

                return { titulo, sku, precio, stock, metodo: 'fallback' };
            }
        """)

        await browser.close()

        return {
            "titulo": data.get("titulo", "").strip(),
            "sku":    data.get("sku",    "").strip(),
            "precio": formatear_precio(data.get("precio", "")),
            "stock":  data.get("stock",  "Desconocido"),
            "metodo": data.get("metodo", ""),
        }


def formatear_precio(raw: str) -> str:
    if not raw:
        return ""
    num_str = re.sub(r"[^\d.]", "", str(raw))
    try:
        num = float(num_str)
        return "$ {:,.2f}".format(num).replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return raw


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({"status": "ok", "mensaje": "Bancor Scraper corriendo ✅"})

@app.route("/scrape")
def scrape_endpoint():
    url = request.args.get("url", "").strip()

    if not url:
        return jsonify({"error": "Falta el parámetro ?url="}), 400

    if not url.startswith("https://tutiendabancor.com/") and \
       not url.startswith("http://tutiendabancor.com/"):
        return jsonify({"error": "URL no permitida"}), 403

    try:
        resultado = asyncio.run(scrape(url))
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e), "titulo": "ERROR", "sku": "", "precio": "", "stock": ""}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
