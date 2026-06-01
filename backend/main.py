from playwright.async_api import async_playwright
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel
import httpx

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "null"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return RedirectResponse(url="/app/")

# Serve frontend at /app
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

JOB_TITLE = "Verification team"
ORGANISATION_NAME = "Aspora"
CHECK_REASON = "Personal finance (including bank and building society accounts, loans, credit cards and mortgages)"

BASE_URL = "https://view-immigration-status.service.gov.uk"


class CheckRequest(BaseModel):
    share_code: str
    date_of_birth: str  # YYYY-MM-DD


async def click_continue(page):
    await page.locator('button:visible:has-text("Continue")').click()
    await page.wait_for_load_state("networkidle", timeout=30000)


def extract_summary_field(rows: list, key: str):
    for row in rows:
        if row.get("key", "").lower() == key.lower():
            return row.get("value")
    return None


@app.post("/api/check-immigration-status")
async def check_status(payload: CheckRequest):
    share_code = payload.share_code.replace(" ", "").upper()
    parts = payload.date_of_birth.split("-")
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Date must be in YYYY-MM-DD format")
    year, month, day = parts

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # Step 1: Share code
            await page.goto(f"{BASE_URL}/view/checker-details", wait_until="networkidle")
            await page.fill('input[name="shareCode"]', share_code)
            await click_continue(page)

            # Step 2: Date of birth
            await page.fill('input[name="dob-day"]', day.lstrip("0") or "0")
            await page.fill('input[name="dob-month"]', month.lstrip("0") or "0")
            await page.fill('input[name="dob-year"]', year)
            await click_continue(page)

            # Check for DOB/share code mismatch error
            error_summary = await page.query_selector(".govuk-error-summary")
            if error_summary:
                error_text = await error_summary.inner_text()
                await browser.close()
                return {"success": False, "error": error_text.strip()}

            # Step 3: Job title + organisation
            await page.fill('input[name="jobTitle"]', JOB_TITLE)
            await page.fill('input[name="companyName"]', ORGANISATION_NAME)
            await click_continue(page)

            # Step 4: Reason for check
            await page.locator(f'input[type="radio"][value="{CHECK_REASON}"]').click()
            await click_continue(page)

            # --- Check for error page after all steps ---
            if "/error/" in page.url or "problem" in (await page.title()).lower():
                error_text = await page.inner_text("main")
                await browser.close()
                return {"success": False, "error": error_text.strip()[:300]}

            # Also catch any late-stage error summaries
            error_summary = await page.query_selector(".govuk-error-summary")
            if error_summary:
                error_text = await error_summary.inner_text()
                await browser.close()
                return {"success": False, "error": error_text.strip()}

            # Wait explicitly for summary list to be present
            try:
                await page.wait_for_selector(".govuk-summary-list__row", timeout=10000)
            except Exception:
                pass

            # Summary list rows (Name, DOB, Nationality, Status, Valid from, Valid until)
            row_elements = await page.query_selector_all(".govuk-summary-list__row")
            summary_rows = []
            for row in row_elements:
                key_el = await row.query_selector(".govuk-summary-list__key")
                val_el = await row.query_selector(".govuk-summary-list__value")
                if key_el and val_el:
                    summary_rows.append({
                        "key": (await key_el.inner_text()).strip(),
                        "value": (await val_el.inner_text()).strip(),
                    })

            # Photo — base64 src from <img id="photo">
            photo_src = None
            photo_el = await page.query_selector("img#photo")
            if photo_el:
                photo_src = await photo_el.get_attribute("src")

            # PDF link
            pdf_link = None
            pdf_el = await page.query_selector('a[aria-label="Download PDF"]')
            if pdf_el:
                href = await pdf_el.get_attribute("href")
                pdf_link = BASE_URL + href if href and href.startswith("/") else href

            # Cookies for authenticated PDF download
            cookies = await page.context.cookies()

            await browser.close()

            # Build response
            name = extract_summary_field(summary_rows, "Name")
            status = extract_summary_field(summary_rows, "Status")
            valid_from = extract_summary_field(summary_rows, "Valid from")
            valid_until = extract_summary_field(summary_rows, "Valid until")

            return {
                "success": True,
                "name": name,
                "status": status,
                "valid_from": valid_from,
                "valid_until": valid_until,
                "photo": photo_src,  # data:image/jpeg;base64,... or None
                "pdf_url": "/api/download-pdf" if pdf_link else None,
                "pdf_source_url": pdf_link,
                "summary_rows": summary_rows,
                "cookies": [{"name": c["name"], "value": c["value"], "domain": c["domain"]} for c in cookies],
            }

        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/download-pdf")
async def download_pdf(body: dict):
    """Proxy the PDF download using the session cookies from the check."""
    pdf_url = body.get("pdf_source_url")
    cookies = body.get("cookies", [])
    if not pdf_url:
        raise HTTPException(status_code=400, detail="Missing pdf_source_url")

    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(
            pdf_url,
            headers={
                "Cookie": cookie_header,
                "Referer": BASE_URL,
            },
            timeout=30,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="PDF download failed")

    return Response(
        content=resp.content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="immigration-status.pdf"'},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
