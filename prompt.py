STAGE1_PROMPT = """
Real Estate Listing Extraction AI

(i)Provide rates on net carpet area property categoty (Flat / Shop/Office/Land) wise.
(ii) Consider the exact coordinate while Deriving rates.

Location: {location}
Latitude: {latitude}
Longitude: {longitude}

EXTRACTION RULES & PRIORITIES:
1. Constraints: Do not estimate prices, summarize, predict, or merge listings from different projects. If multiple transactions are found for the same project, average the transaction rates and use the averaged rate as the project rate. Do not average transactions across different projects.
2. Location Priority: Exact project -> Within 500m -> Within 1km -> Same micro-market. Do not include listings from other micro-markets.
3. Categories: Collect listings for Residential Flat, Office, Retail Shop, and Land/Plot.
4. Area Basis: For Flats/Offices/Shops, prefer Net Carpet Area -> Carpet Area -> Built-up Area -> Super Built-up Area. Preserve the original area type exactly as reported. If the transaction is not reported on Net Carpet Area, convert the rate to Net Carpet Area and return the normalized Net Carpet Rate. If the area basis is Built-up Area, convert it to Net Carpet Area by dividing the Built-up Area by 1.2 before calculating the Net Carpet Rate. For Land, preserve units exactly as reported.
5. Calculated Rate: If both Price and Area are available, calculate Rate = Price / Area. If the transaction is not on Net Carpet Area, convert it to Net Carpet Area before calculating the final rate. Otherwise, leave null.
6. Distance: You MUST extract or reasonably estimate 'Distance from Coordinate' based on locality.
7. Commercial: You MUST actively search for and extract OFFICE space and RETAIL shops. Do not ignore commercial listings.
8. Exhaustiveness: Extract ALL available listings. Return at least 5 transactions for every property category if available in the search results. If more transactions exist, return all of them.
9. SOURCE URL (CRITICAL): Every transaction MUST contain its own exact, complete source URL (starting with http/https). Do NOT leave the "url" field empty. The user needs the exact link as evidence.

REQUIREMENTS:
1. Output the ENTIRE response as raw, valid JSON matching the exact structure below.
2. DO NOT wrap it in markdown code blocks like ```json. Just return the JSON object.

{{
  "location_identification": {{
    "latitude":"", "longitude":"", "identified_location":"",
    "nearest_locality":"", "sector_or_area":"", "micro_market":"",
    "city":"", "state":"", "country":""
  }},
  "property_categories": {{
    "residential": [
      {{
        "project_name":"",
        "property_type":"Flat",
        "listing_type":"",
        "average_project_rate":"",
        "rate_unit":"",
        "portal":"",
        "distance_from_coordinate":"",
        "transactions":[
          {{
            "total_price":"",
            "area":"",
            "area_unit":"",
            "area_basis":"",
            "calculated_rate":"",
            "normalized_net_carpet_rate":"",
            "url":""
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
Price Trend Micromarket

Provide rate trend on net carpet area property category (Flat / Shop / Office / Land) wise for the last 3 years in the same micromarket.

Location: {location}
Latitude: {latitude}
Longitude: {longitude}

REQUIREMENTS:
1. Present the result strictly following this UNIVERSAL HTML FORMAT:
   - Main Header: Use <h2> for the overall title.
   - Summary/Intro: Provide a short introductory paragraph explaining the location/micromarket.
   - Tables: Present the trend data in a <table>. The table MUST have these exact columns: Property Category, 2024 Rate ₹/sq.ft (Price in range), 2025 Rate ₹/sq.ft (Price in range), 2026 Rate ₹/sq.ft (Price in range), Trend.
   - Explanations & Sources: Below the table, include a summary paragraph of the analysis and the exact source link (<a>).
   - Separators: Use horizontal rules (<hr>) between major blocks if needed.
3. SOURCE URL (CRITICAL): You MUST explicitly show the exact Source of info as well (include the exact URLs as clickable links). Do NOT leave links empty. The user needs the exact link as evidence.
4. Output the ENTIRE response as raw, valid HTML. DO NOT wrap it in markdown code blocks like ```html. Just return the raw HTML tags (e.g., <div>, <table>, <p>, <a>).
5. Use Tailwind CSS classes in your HTML tags to style the tables and text nicely so it fits a dark mode theme. (e.g., <table class="w-full text-sm text-left text-gray-300 mb-6">, <th class="px-4 py-2 border-b border-gray-600 text-gray-100">, <td class="px-4 py-2 border-b border-gray-700">, <a class="text-blue-400 hover:underline" target="_blank">).
6. DO NOT output JSON. DO NOT output Markdown. ONLY output valid HTML.
7. ALL links MUST include target="_blank" so they open in a new tab.
8. CRITICAL: DO NOT include <html>, <head>, <body>, <style>, or <script> tags. Only output the content elements (like <div>, <table>, <h3>, <p>, <a>).
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