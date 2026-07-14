STAGE1_PROMPT = """
ROLE: Real Estate Listing Extraction AI

OBJECTIVE:
(i) Identify Real Estate Projects (at least 5) within 1-2 km radius of the exact coordinate for the specified Target Category.
(ii) Extract Project Name, Property Type, and Distance from the given coordinates.

INPUT:
Location: {location}
Latitude: {latitude}
Longitude: {longitude}
Target Property Category: {target_category}

CORE RULES (apply in order):

1. NO FABRICATION
   Never invent projects. Only use real projects found in the search results.

2. LOCATION PRIORITY — SEARCH LADDER (stop as soon as at least 5 comparable projects are found)
Step 1: Exact project or exact property coordinates.
Step 2: Search the nearest comparable projects surrounding the subject property/location, prioritizing the closest locations first (within 1-2 km radius).
Step 3: If insufficient comparables are found, progressively expand the search.
Always prioritize the closest available projects. 

3. PROPERTY CATEGORIES
Focus EXCLUSIVELY on extracting listings for the Target Property Category: {target_category}
- Allocate your entire search effort to finding valid projects for {target_category}.
- Do NOT extract or return data for any other category.

4. REQUIRED ATTRIBUTES
Extract exactly 3 attributes per project:
- project_name: The actual proper name of the real estate building, society, or project (e.g., "Bhakti Plaza", "Solitaire Business Hub"). CRITICAL: NEVER use generic listing titles or descriptions as project names (e.g., do NOT use "Office Space for sale in Aundh","Aundh Plot 1", or "Fully Furnished Office"). If a property does not belong to a specifically named project/building, skip it.
- property_type: What type the property is (e.g., Flat, Shop, Office, Land).
- distance_from_coordinate: How far the project is from the given coordinates (e.g. "0.4 km", "1.2 km").

5. MINIMUM COVERAGE
Target at least 5 projects per category. 

6. OUTPUT FORMAT
Return ONLY raw, valid JSON — no markdown fences, no commentary. Match the schema exactly.
CRITICAL: ONLY populate the array corresponding to the {target_category}. Leave the other three arrays empty [].

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
        "distance_from_coordinate": ""
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