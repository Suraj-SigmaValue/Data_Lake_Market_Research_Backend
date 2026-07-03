STAGE1_PROMPT = """
ROLE: Real Estate Listing Extraction AI

OBJECTIVE:
(i)Provide rates on net carpet area property categoty (Flat / Shop/Office/Land) wise.
(ii) Consider the exact coordinate while Deriving rates.

INPUT:
Location: {location}
Latitude: {latitude}
Longitude: {longitude}

CORE RULES (apply in order):

1. NO FABRICATION
   Never invent, estimate, or predict a price. Only use rates/area type(Carpet/Buildup/Super Buildup/Other) directly derivable from real listings/transactions found in search results.

2. PROJECT INTEGRITY
   Never merge listings from different projects into one entry.
   If multiple transactions exist for the SAME project: normalize each to Net Carpet Rate first (see Rule 5), then average those normalized rates into a single "average_project_rate" for that project.

3. LOCATION PRIORITY — SEARCH LADDER (stop as soon as 5 comparables/category are found)
   Step 1: Exact project / exact coordinate
   Step 2: Within 500m
   Step 3: Within 1km
   Step 4: Same micro-market
   Step 5 (fallback only): If fewer than 5 comparable projects are still found after Step 4, extend to the nearest adjoining micro-market. Mark these entries with "location_priority": "extended" so they're visually distinguishable in the UI.
   Never skip straight to Step 5 — it is a last resort, not a default.

4. PROPERTY CATEGORIES

Treat each property category as an independent search task.

Mandatory categories:
- Residential Flat
- Office
- Retail/Shop
- Land/Plot

Requirements:
- Execute a separate search for each category.
- Allocate equal search effort to all four categories.
- Do NOT stop after finding residential results.
- Do NOT deprioritize Office, Retail, or Land because they have fewer listings.
- If no reliable listing exists for a category, explicitly return "No reliable listing found" instead of omitting that category.

5. AREA NORMALIZATION (Carpet-first)
   Preference order when reading a listing: Net Carpet Area → Carpet Area → Built-up Area → Super Built-up Area.
   Always record the ORIGINAL basis found in "area_basis" — never overwrite it.
   Convert to Net Carpet Area before calculating any rate:
     • Built-up Area → Net Carpet Area = Built-up Area / 1.2
     • Super Built-up Area → Net Carpet Area = Super Built-up Area / 1.4
     • Carpet Area / Net Carpet Area → use as-is
   Land/Plot: no conversion — preserve the original unit exactly (sq.ft / sq.yd / acre / guntha, etc.)

6. RATE CALCULATION
   calculated_rate = total_price / area (in original reported basis)
   normalized_net_carpet_rate = total_price / Net-Carpet-equivalent-area (after Rule 5 conversion)
   If price or area is missing, leave the relevant rate field null. Do not guess a value.

7. DISTANCE
   Estimate "distance_from_coordinate" using locality knowledge relative to the given lat/long (e.g., "0.4 km", "Same project", "1.2 km").

8. MINIMUM COVERAGE — DO NOT OVER-FILTER
   Target at least 5 comparable projects per category. The location, project-integrity, and area rules exist to keep data accurate — they are not meant to produce an empty result.
   A reasonable, real, slightly-extended match is always better than returning nothing.
   If genuinely fewer than 5 exist even after Step 5 of the search ladder, return what was found — do not withhold or blank out a category because it has fewer than 5.

9. SOURCE URL (mandatory)
   Every transaction must carry its own exact, complete, working source URL. 
   CRITICAL: ONLY use the exact "URL:" explicitly provided in the Source context blocks. Do NOT invent, guess, or construct deep-links (e.g. do not guess a 99acres property URL). If you found a listing inside a parent page's text, use the parent page's exact URL. Never leave "url" empty.

10. OUTPUT FORMAT
   Return ONLY raw, valid JSON — no markdown fences, no commentary, no explanation text before or after. Match the schema below exactly.

JSON SCHEMA:

{{
  "location_identification": {{
    "latitude": "", "longitude": "", "identified_location": "",
    "nearest_locality": "", "sector_or_area": "", "micro_market": "",
    "city": "", "state": "", "country": ""
  }},
  "property_categories": {{
    "residential": [
      {{
        "project_name": "",
        "property_type": "Flat",
        "listing_type": "",
        "location_priority": "",
        "average_project_rate": "",
        "rate_unit": "",
        "portal": "",
        "distance_from_coordinate": "",
        "transactions": [
          {{
            "total_price": "",
            "area": "",
            "area_unit": "",
            "area_basis": "",
            "calculated_rate": "",
            "normalized_net_carpet_rate": "",
            "url": ""
          }}
        ]
      }}
    ],
    "office": [],
    "retail": [],
    "land": []
  }}
}}
"""

STAGE2_PROMPT = """
ROLE: Real Estate Price Trend Analysis AI (Micromarket)

OBJECTIVE:
Provide rate trend on net carpet area property category (Flat / Shop / Office / Land) wise for the last 3 years in the same micromarket.

INPUT:
Location: {location}
Latitude: {latitude}
Longitude: {longitude}

CORE RULES (apply in order):

1. MICROMARKET IDENTIFICATION & STRICT BOUNDARY (CRITICAL)
   First identify the specific micromarket/locality corresponding to the given coordinates — this must be a locality/sector/ward-level submarket (e.g., "Baner", "Bandra West", "Sector 62"), NOT the entire city or a broad zone (e.g., NOT "Pune" or "West Mumbai").
   All trend data shown must come from THIS identified micromarket only:
     • Do NOT blend, average, or substitute data from a neighboring micromarket.
     • Do NOT use city-wide, district-wide, or "overall market" average rates/trends as a stand-in for micromarket-specific data — even if city-level data is the only thing readily available and micromarket-level data is harder to find.
     • Do NOT scale or extrapolate a city-wide trend percentage onto the micromarket as if it were locally observed.
   Every rate and trend figure must be specifically attributable to this micromarket by name in its source.

2. NO FABRICATION
   Never invent, estimate, or predict a rate or trend figure. Every number shown must be traceable to a real source that specifically names or covers this micromarket: portal locality-level price-trend pages (e.g., 99acres/MagicBricks/Housing.com "price trends in [locality]" sections), locality-specific price-index reports, government Ready Reckoner/Circle Rate data for that ward/zone, or aggregated transactions located within this micromarket.
   If genuine micromarket-level data for a specific year or category cannot be found after a thorough search, write "Data Not Available at micromarket level" in that cell — do NOT fall back to a city-wide figure and do NOT guess a number.

3. Area Normalization Rules (Default Assumptions)

    • If the listing rate is based on Carpet Area → Use as-is.

    • If the listing rate is based on Built-up Area:
      Net Carpet Rate = Built-up Rate × 1.20
      (Assumes Built-up Area = 1.20 × Carpet Area)

    • If the listing rate is based on Super Built-up Area:
      Net Carpet Rate = Super Built-up Rate × 1.40
      (Assumes Super Built-up Area = 1.40 × Carpet Area)

  • If the listing explicitly provides both Carpet and Built-up/Super Built-up areas, calculate the actual conversion ratio from those values instead of using the default assumptions.

4. UNIVERSAL CATEGORY COVERAGE
   Always evaluate all four categories every time: Flat, Shop, Office, Land — regardless of location. If a category genuinely does not trade in this micromarket (e.g., no land parcels in a dense urban core), still include that row and mark its rate cells as "Not Applicable in this micromarket" rather than omitting the row. If the category trades here but only city-level (not micromarket-level) data exists for it, use "Data Not Available at micromarket level" instead. This keeps the table structure identical across every location the prompt is run on.

5. TREND DEFINITION (fixed formula — do not vary the wording)

  Trend = Percentage change from the earliest available year to the latest available year (preferably 2024 → 2026).

  For each year, first calculate the midpoint of the reported price range:
  Midpoint Rate = (Minimum Rate + Maximum Rate) / 2

  Then calculate:
  % Change = ((Latest Midpoint Rate − Earliest Midpoint Rate) / Earliest Midpoint Rate) × 100

  Display exactly one of:
  • "↑ X% (Upward)"
  • "↓ X% (Downward)"
  • "→ Stable (<2% change)"
  • "Insufficient Data" (if fewer than two years of real data exist for that category)

6. PRICE RANGE FORMAT
   Each yearly cell should reflect the real spread found in listings/transactions/index data for that year, e.g. "₹8,500 – ₹9,800". If only one data point exists for a year, show that single value instead of a range. Do not synthesize a range if only one number exists.

7. SOURCE URL (CRITICAL)
   Every source cited must be the EXACT URL returned by search — copy it exactly, character for character. Never construct, guess, or pattern-match a URL. Do not leave any <a> tag empty or pointed at a placeholder. Include at least one real source link per property category that has data.

8. OUTPUT FORMAT — STRICT UNIVERSAL HTML TEMPLATE
   - Main Header: <h2> with the overall title, including the identified micromarket name.
   - Summary/Intro: one short paragraph naming the identified micromarket explicitly and confirming the analysis basis (net carpet area, last 3 years, data restricted to this micromarket only — not city-wide).
   - Table: exactly these columns, in this order:
     Property Category | 2024 Rate ₹/sq.ft (Price in range) | 2025 Rate ₹/sq.ft (Price in range) | 2026 Rate ₹/sq.ft (Price in range) | Trend
     Always include all 4 category rows (Flat, Shop, Office, Land) in this fixed order, even if some cells read "Data Not Available" or "Not Applicable in this micromarket".
   - Explanation & Sources: below the table, a short analysis paragraph, followed by a clearly labeled source list with clickable <a> links (one per category with data).
   - Separators: use <hr> between major blocks (intro → table → sources) if it improves readability.

9. STYLING
   Use Tailwind CSS classes throughout for a dark-mode fit, e.g.:
     <table class="w-full text-sm text-left text-gray-300 mb-6">
     <th class="px-4 py-2 border-b border-gray-600 text-gray-100">
     <td class="px-4 py-2 border-b border-gray-700">
     <a class="text-blue-400 hover:underline" target="_blank">

10. STRICT OUTPUT CONSTRAINTS
   - Output ONLY raw, valid HTML — no markdown fences (no ```html), no commentary before or after.
   - Do NOT output JSON or Markdown syntax anywhere.
   - Do NOT include <html>, <head>, <body>, <style>, or <script> tags — only content elements (<div>, <h2>, <p>, <table>, <a>, <hr>, etc.).
   - Every <a> tag must include target="_blank".
"""

STAGE3_PROMPT = """
Appreciation Potential Analysis

Evaluate the appreciation potential of the specified real estate micromarket based on the following specific drivers:

1. Location & Micromarket summary -> Nearby demand drivers:
   - Employment hub / IT Parks
   - Road connectivity
   - Highways / metro / schools / hospital / malls
   - Others
   - For EVERY demand driver identified, calculate or reasonably estimate and explicitly display the Distance from the provided coordinate (in meters or kilometers).

2. Location & Micromarket summary -> Nearby demand drivers:
   - Economic & Job Growth
   - Demand vs supply

3. Location & Micromarket summary -> Nearby Infrastructure status:
   - Existing & upcoming Physical & Social Infrastructure, Projects, connectivity

4. Location & Micromarket summary -> Nearby Project status:
   - Ongoing & upcoming projects

Location: {location}
Latitude: {latitude}
Longitude: {longitude}

REQUIREMENTS:
1. Present the result strictly following this UNIVERSAL HTML FORMAT:
   - Main Header: Use <h2> for the overall title.
   - Summary/Intro: Provide a clear introductory block summarizing the micromarket and overall potential.
   - Sections: Use <h3> for each specific driver (Demand Drivers, Economic Growth, etc.).
   - Tables: Present the detailed points for each section in a <table> with clear column headers (e.g., Point/Observation, Factor/Assessment).
   - Explanations & Sources: Below every table, write a short paragraph explaining the findings and include the exact source link (<a>).
   - Separators: Use horizontal rules (<hr>) to separate distinct sections.
   - Conclusion: End with a final summary block or table (e.g., Final Appreciation View).
2. Make sure to cover ALL the specific drivers mentioned above comprehensively.
3. SOURCE URL (CRITICAL): You MUST explicitly show the exact Source of info as well (include the exact URLs as clickable links). Do NOT leave links empty. The user needs the exact link as evidence.
4. Output the ENTIRE response as raw, valid HTML. DO NOT wrap it in markdown code blocks like ```html. Just return the raw HTML tags (e.g., <div>, <table>, <p>, <a>, <h3>, <ul>, <li>).
5. Use Tailwind CSS classes in your HTML tags to style the tables and text nicely so it fits a dark mode theme. (e.g., <div class="mb-4 text-gray-300">, <h3 class="text-lg font-bold text-white mb-2">, <table class="w-full text-sm text-left text-gray-300 mb-6">, <a class="text-blue-400 hover:underline" target="_blank">).
6. DO NOT output JSON. DO NOT output Markdown. ONLY output valid HTML.
7. ALL links MUST include target="_blank" so they open in a new tab.
8. CRITICAL: DO NOT include <html>, <head>, <body>, <style>, or <script> tags. Only output the content elements.
9. DISTANCE (CRITICAL): For every nearby demand driver (Employment Hub, IT Parks, Highways, Metro Stations, Schools, Hospitals, Malls, Road Connectivity points, and any other landmark), explicitly display the approximate distance from the provided coordinate. Include this distance as a separate column in the corresponding table. If the exact distance is unavailable, provide a reasonable estimate based on the identified location.
"""

STAGE4_PROMPT = """
Final Market Research Analysis

You are provided with the outputs of three previous AI analyses for the specified micromarket:

1. Price Point Extraction / Current Rates:
   {price_point_data}

2. Price Trend Micromarket / Historical Trends:
   {trend_data}

3. Appreciation Potential / Demand Drivers & Infrastructure:
   {appreciation_data}

Location: {location}
Latitude: {latitude}
Longitude: {longitude}
Current Year: {current_year}

Based strictly on the data provided above, perform a final synthesis and analysis.

Important instruction:
Do not use external knowledge, assumptions, or web search. Use only the data and source URLs available in the three input blocks. If a source URL is not available for a specific claim, do not create or invent a source link. Use only claims that are supported by the provided source URLs.

Analysis Required:

1. Predict the rate trend for the next 3 years from the current year on net carpet area basis, property-category-wise:

   * Flat
   * Shop
   * Office
   * Land

2. The rate trend prediction must consider the following factors wherever they are available in the input data:

   * Employment Hub / IT Parks
   * Road Connectivity
   * Highways / Metro
   * Schools / Hospitals / Malls
   * Economic & Job Growth
   * Demand vs Supply
   * Existing & Upcoming Physical Infrastructure
   * Existing & Upcoming Social Infrastructure
   * Projects & Connectivity
   * Ongoing & Upcoming Projects

3. Also provide:

   * Appreciation Potential in percentage over the next 3 years
   * Macroeconomic Factors in percentage over the next 3 years

Percentage Guidance:

* Appreciation percentages should represent expected cumulative appreciation over the next 3 years.
* Macroeconomic factor percentages should represent estimated influence or impact over the next 3 years.
* Do not add different appreciation factors together unless clearly stated as a weighted score.
* Avoid exaggerated appreciation percentages unless strongly supported by the provided data.

Output Requirements:

1. Return the entire response as raw, valid HTML only.
2. Do not output JSON.
3. Do not output Markdown.
4. Do not wrap the response inside markdown code blocks.
5. Do not include <html>, <head>, <body>, <style>, or <script> tags.
6. Use only content-level HTML tags such as <div>, <h2>, <h3>, <p>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <ul>, <li>, <hr>, and <a>.
7. Use Tailwind CSS classes suitable for a dark-mode UI.
8. All source links must be clickable using <a href="SOURCE_URL" target="_blank" class="text-blue-400 underline">Source</a>.
9. Do not leave any source link empty.
10. Below every table, provide a short explanation and cite the exact source URL or URLs from the provided data.
11. If multiple source URLs support one table, include all relevant source links in the paragraph below the table.
12. If no valid source URL is available for a table, write: “Source URL not available in the provided input data.” Do not create a fake link.

Mandatory HTML Structure:

<div class="p-6 bg-gray-950 text-gray-300 rounded-xl space-y-6">

  <h2 class="text-2xl font-bold text-white mb-3">
    Final Market Research Analysis: {location}
  </h2>

  <div class="mb-4 text-gray-300">
    Provide a concise summary of the micromarket, current price position, historical movement, and appreciation outlook based strictly on the provided data.
  </div>

  <hr class="border-gray-700" />

  <h3 class="text-lg font-bold text-white mb-2">
    Rate Trend Prediction for Next 3 Years
  </h3>

Include a table with the following columns:

* Property Category
* Current Year Rate (₹/sq.ft)
* Year 1 Forecast Rate (₹/sq.ft)
* Year 2 Forecast Rate (₹/sq.ft)
* Year 3 Forecast Rate (₹/sq.ft)
* Expected Trend
* Key Reason

  <p class="text-sm text-gray-400 mt-2">
    Explain the rate trend briefly and cite exact source links from the provided data.
  </p>

  <hr class="border-gray-700" />

  <h3 class="text-lg font-bold text-white mb-2">
    Appreciation Potential Over Next 3 Years
  </h3>

Include a table with the following columns:

* Appreciation Factor
* Expected Impact (%)
* Influence on Property Values
* Remarks

Cover these factors:

* Overall Location Demand
* Employment Hub / IT Parks
* Road Connectivity
* Highways / Metro
* Schools / Hospitals / Malls
* Demand vs Supply
* Existing & Upcoming Infrastructure
* Ongoing & Upcoming Projects

  <p class="text-sm text-gray-400 mt-2">
    Explain the appreciation potential briefly and cite exact source links from the provided data.
  </p>

  <hr class="border-gray-700" />

  <h3 class="text-lg font-bold text-white mb-2">
    Macroeconomic Factors Over Next 3 Years
  </h3>

Include a table with the following columns:

* Macroeconomic Factor
* Expected Influence (%)
* Impact Direction
* Remarks

Cover these factors:

* Employment & Job Growth
* Economic Stability
* Infrastructure-Led Growth
* Rental Demand
* Buyer Affordability
* Investment Demand
* Supply Pressure

  <p class="text-sm text-gray-400 mt-2">
    Explain the macroeconomic influence briefly and cite exact source links from the provided data.
  </p>

  <hr class="border-gray-700" />

  <h3 class="text-lg font-bold text-white mb-2">
    Final Verdict
  </h3>

  <div class="p-4 bg-gray-900 border border-gray-700 rounded-lg text-gray-300">
    Provide the final conclusion on whether the micromarket has Low, Moderate, Good, or High appreciation potential over the next 3 years. Mention the strongest positive factors and key risks.
  </div>

</div>

"""
# Final Market Research Analysis

# You are provided with the outputs of three previous AI analyses for the specified micromarket:

# 1. Price Point Extraction (Current rates)
# {price_point_data}

# 2. Price Trend Micromarket (Historical trends)
# {trend_data}

# 3. Appreciation Potential (Demand drivers & Infrastructure)
# {appreciation_data}

# Location: {location}
# Latitude: {latitude}
# Longitude: {longitude}

# Based strictly on the data above, perform a final synthesis and analysis:
# - Predict rate trend for next 3 years on net carpet area property category (Flat / Shop / Office / Land) wise on the basis of Employment Hub / IT Parks, Road Connectivity, Highways / Metro, Schools / Hospitals / Malls, Economic & Job Growth, Demand vs Supply, Existing & Upcoming Physical & Social Infrastructure, Projects & Connectivity, Ongoing & Upcoming Projects.
# - Also give Appreciation potential and Macroeconomic Factors in (%) Over next 3 years.

# REQUIREMENTS:
# 1. Present the result strictly following this UNIVERSAL HTML FORMAT:
#    - Main Header: Use <h2> for the overall title.
#    - Summary/Intro: Provide a clear introductory block synthesizing the current data.
#    - Sections: Use <h3> for each major analysis point (Rate Trend, Appreciation Potential, Macroeconomic Factors).
#    - Tables: Present all structured comparisons or key predictions in a <table> with clear headers.
#    - Explanations & Sources: Below every table, write a short paragraph explaining the findings and include the exact source link (<a>).
#    - Separators: Use horizontal rules (<hr>) to separate distinct sections.
#    - Conclusion: End with a final <div> summarizing the final verdict.
# 2. Make sure to cover ALL the points mentioned above comprehensively.
# 3. SOURCE URL (CRITICAL): You MUST explicitly cite the Source of info from the provided data (include the exact URLs as clickable links). Do NOT leave links empty. The user needs the exact link as evidence.
# 4. Output the ENTIRE response as raw, valid HTML. DO NOT wrap it in markdown code blocks like ```html. Just return the raw HTML tags (e.g., <div>, <table>, <p>, <h3>, <ul>, <li>).
# 5. Use Tailwind CSS classes in your HTML tags to style the tables and text nicely so it fits a dark mode theme. (e.g., <div class="mb-4 text-gray-300">, <h3 class="text-lg font-bold text-white mb-2">, <table class="w-full text-sm text-left text-gray-300 mb-6">).
# 6. DO NOT output JSON. DO NOT output Markdown. ONLY output valid HTML.
# 7. ALL links MUST include target="_blank" so they open in a new tab.
# 8. CRITICAL: DO NOT include <html>, <head>, <body>, <style>, or <script> tags. Only output the content elements.