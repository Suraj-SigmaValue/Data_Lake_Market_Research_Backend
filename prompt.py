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
4. Area Basis: For Flats/Offices/Shops, prefer Net Carpet Area -> Carpet Area -> Built-up Area -> Super Built-up Area. Preserve the original area type exactly as reported. If the transaction is not reported on Net Carpet Area, convert the rate to Net Carpet Area and return the normalized Net Carpet Rate. For Land, preserve units exactly as reported.
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
1. Present the result strictly in a TABULAR form (using an HTML <table>).
2. Include a summary of the analysis below the table.
3. SOURCE URL (CRITICAL): You MUST explicitly show the exact Source of info as well (include the exact URLs as clickable links). Do NOT leave links empty. The user needs the exact link as evidence.
4. Output the ENTIRE response as raw, valid HTML. DO NOT wrap it in markdown code blocks like ```html. Just return the raw HTML tags (e.g., <div>, <table>, <p>, <a>).
5. Use Tailwind CSS classes in your HTML tags to style the tables and text nicely so it fits a dark mode theme. (e.g., <table class="w-full text-sm text-left text-gray-300 mb-6">, <th class="px-4 py-2 border-b border-gray-600 text-gray-100">, <td class="px-4 py-2 border-b border-gray-700">, <a class="text-blue-400 hover:underline">).
6. DO NOT output JSON. DO NOT output Markdown. ONLY output valid HTML.
7. CRITICAL: DO NOT include <html>, <head>, <body>, <style>, or <script> tags. Only output the content elements (like <div>, <table>, <h3>, <p>, <a>).
"""

STAGE3_PROMPT = """
Appreciation Potential Analysis

Evaluate the appreciation potential of the specified real estate micromarket based on the following specific drivers:

1. Location & Micromarket summary -> Nearby demand drivers:
   - Employment hub / IT Parks
   - Road connectivity
   - Highways / metro / schools / hospital / malls
   - Others

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
1. Present the result strictly in a clear, highly-readable format (use HTML <table> for comparisons or lists/cards <div> for sections). 
2. Make sure to cover ALL the points mentioned above comprehensively.
3. SOURCE URL (CRITICAL): You MUST explicitly show the exact Source of info as well (include the exact URLs as clickable links). Do NOT leave links empty. The user needs the exact link as evidence.
4. Output the ENTIRE response as raw, valid HTML. DO NOT wrap it in markdown code blocks like ```html. Just return the raw HTML tags (e.g., <div>, <table>, <p>, <a>, <h3>, <ul>, <li>).
5. Use Tailwind CSS classes in your HTML tags to style the tables and text nicely so it fits a dark mode theme. (e.g., <div class="mb-4 text-gray-300">, <h3 class="text-lg font-bold text-white mb-2">, <table class="w-full text-sm text-left text-gray-300 mb-6">, <a class="text-blue-400 hover:underline">).
6. DO NOT output JSON. DO NOT output Markdown. ONLY output valid HTML.
7. CRITICAL: DO NOT include <html>, <head>, <body>, <style>, or <script> tags. Only output the content elements.
"""

STAGE4_PROMPT = """
Final Market Research Analysis

You are provided with the outputs of three previous AI analyses for the specified micromarket:

1. Price Point Extraction (Current rates)
{price_point_data}

2. Price Trend Micromarket (Historical trends)
{trend_data}

3. Appreciation Potential (Demand drivers & Infrastructure)
{appreciation_data}

Location: {location}
Latitude: {latitude}
Longitude: {longitude}

Based strictly on the data above, perform a final synthesis and analysis:
- Predict rate trend for next 3 years on net carpet area property category (Flat / Shop / Office / Land) wise on the basis of Employment Hub / IT Parks, Road Connectivity, Highways / Metro, Schools / Hospitals / Malls, Economic & Job Growth, Demand vs Supply, Existing & Upcoming Physical & Social Infrastructure, Projects & Connectivity, Ongoing & Upcoming Projects.
- Also give Appreciation potential and Macroeconomic Factors in (%) Over next 3 years.

REQUIREMENTS:
1. Present the result strictly in a highly-readable format (use HTML <table> for comparisons or lists/cards <div> for sections). 
2. Make sure to cover ALL the points mentioned above comprehensively.
3. SOURCE URL (CRITICAL): You MUST explicitly cite the Source of info from the provided data (include the exact URLs as clickable links). Do NOT leave links empty. The user needs the exact link as evidence.
4. Output the ENTIRE response as raw, valid HTML. DO NOT wrap it in markdown code blocks like ```html. Just return the raw HTML tags (e.g., <div>, <table>, <p>, <h3>, <ul>, <li>).
4. Use Tailwind CSS classes in your HTML tags to style the tables and text nicely so it fits a dark mode theme. (e.g., <div class="mb-4 text-gray-300">, <h3 class="text-lg font-bold text-white mb-2">, <table class="w-full text-sm text-left text-gray-300 mb-6">).
5. DO NOT output JSON. DO NOT output Markdown. ONLY output valid HTML.
6. CRITICAL: DO NOT include <html>, <head>, <body>, <style>, or <script> tags. Only output the content elements.
"""
