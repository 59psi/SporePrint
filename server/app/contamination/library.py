CONTAMINANTS = [
    {
        "id": "trichoderma",
        "common_name": "Green Mold",
        "scientific_name": "Trichoderma harzianum",
        "appearance": "Starts as bright white patches that rapidly turn dark green with powdery sporulation. Often appears at substrate surface edges or around contaminated grain.",
        "growth_speed": "Very fast — can overtake a substrate in 24-48 hours once sporulating",
        "smell": "Strong musty, earthy, sometimes sweet chemical odor",
        "danger_level": "high",
        "stages": [
            {
                "name": "Early white",
                "description": "Dense white mycelium that grows faster than mushroom mycelium. Can be confused with healthy growth but advances more aggressively and has a finer, more uniform texture.",
            },
            {
                "name": "Green sporulation",
                "description": "Patches turn vivid green as spores form. Once green spores are visible, the contamination is well-established and releasing billions of spores.",
            },
        ],
        "action": "Discard once green sporulation is visible. Early white stage may be isolated if caught immediately, but success rate is low. Do not open contaminated containers indoors.",
        "prevention": "Maintain clean spawn, proper pasteurization/sterilization, work in front of flow hood or SAB, minimize grain-to-grain transfers, maintain proper humidity without pooling water.",
        "common_causes": "Insufficient sterilization, dirty spawn, opening containers in contaminated air, excessive moisture on substrate surface, warm stagnant conditions.",
    },
    {
        "id": "cobweb",
        "common_name": "Cobweb Mold",
        "scientific_name": "Dactylium mildew (Cladobotryum spp.)",
        "appearance": "Wispy, grey, cobweb-like growth that floats above the substrate surface. Much less dense than mushroom mycelium — almost translucent.",
        "growth_speed": "Very fast — can cover an entire tub surface in 24 hours",
        "smell": "Faint musty odor, often not noticeable until advanced",
        "danger_level": "medium",
        "stages": [
            {
                "name": "Early wispy growth",
                "description": "Thin, grey, aerial mycelium that appears to float above the substrate. Easily distinguished from the denser, brighter white of healthy mycelium.",
            },
            {
                "name": "Dense grey mat",
                "description": "Thickens into a grey blanket if untreated. May develop small grey or pinkish fruiting bodies.",
            },
        ],
        "action": "Treatable if caught early. Spray affected area directly with 3% hydrogen peroxide. Increase fresh air exchange. Monitor closely for 48 hours. Discard if it returns after treatment.",
        "prevention": "Adequate fresh air exchange, avoid stagnant humid air, proper surface conditions, clean casing material.",
        "common_causes": "Poor air circulation, excessive humidity with no FAE, contaminated casing layer, stagnant air in fruiting chamber.",
    },
    {
        "id": "black_mold",
        "common_name": "Black Mold",
        "scientific_name": "Aspergillus niger",
        "appearance": "Black or very dark green-black powdery spots. Colonies start small and circular, expanding outward with dense dark sporulation.",
        "growth_speed": "Moderate — slower than Trichoderma but persistent",
        "smell": "Musty, stale odor",
        "danger_level": "critical",
        "stages": [
            {
                "name": "Initial colonization",
                "description": "Small dark spots appear on substrate or grain. May initially look brownish before darkening.",
            },
            {
                "name": "Active sporulation",
                "description": "Dense black powdery spore masses. Extremely hazardous — spores are a serious respiratory irritant and allergen.",
            },
        ],
        "action": "DISCARD IMMEDIATELY. Do not attempt to treat. Seal the container before moving it. Dispose of outdoors. Aspergillus spores are a serious respiratory hazard — wear N95 mask when handling.",
        "prevention": "Proper sterilization, HEPA filtration in grow space, control ambient humidity, clean spawn, avoid working with grain in dusty environments.",
        "common_causes": "Contaminated grain, insufficient sterilization pressure/time, exposure to outdoor air with high mold spore counts, immunocompromised grain from wet storage.",
    },
    {
        "id": "bacterial",
        "common_name": "Bacterial Contamination",
        "scientific_name": "Various bacteria (Bacillus, Pseudomonas, etc.)",
        "appearance": "Slimy, wet, discolored patches. May appear as wet-looking grey, yellow, or orange spots. Substrate looks waterlogged in affected areas.",
        "growth_speed": "Fast — spreads quickly through moist substrate",
        "smell": "Sour, fermented, or foul rotten odor — often the first indicator",
        "danger_level": "high",
        "stages": [
            {
                "name": "Early bacterial growth",
                "description": "Wet, slimy spots on grain or substrate. Slight sour smell. Mycelium may slow or stop growing near affected areas.",
            },
            {
                "name": "Advanced infection",
                "description": "Large slimy areas, strong sour/rotten smell, substrate visibly degraded. Mycelium dies back around bacterial colonies.",
            },
        ],
        "action": "Discard if strong sour smell or large slimy areas are present. Minor bacterial spots on grain can sometimes be outrun by aggressive mycelium, but success rate is low.",
        "prevention": "Proper hydration levels (not too wet), adequate sterilization, clean water source, proper grain prep with correct moisture content, avoid standing water.",
        "common_causes": "Over-hydrated grain or substrate, insufficient sterilization, dirty water, contaminated syringes, too-wet substrate from excessive misting.",
    },
    {
        "id": "lipstick_mold",
        "common_name": "Lipstick Mold",
        "scientific_name": "Sporendonema purpurascens",
        "appearance": "Bright pink to red-orange powdery growth. Unmistakable color — looks like someone dusted the substrate with bright pink powder or lipstick.",
        "growth_speed": "Moderate — but extremely persistent once established",
        "smell": "Mild musty odor",
        "danger_level": "critical",
        "stages": [
            {
                "name": "Early pink spots",
                "description": "Small bright pink or coral-colored spots appear on grain or substrate surface.",
            },
            {
                "name": "Established growth",
                "description": "Vivid pink-red powdery colonies expand. Extremely difficult to eliminate once established — spores persist in grow space.",
            },
        ],
        "action": "DISCARD IMMEDIATELY. Lipstick mold spores are extremely persistent in the environment. Deep clean and disinfect entire grow area. Consider replacing HEPA filters and any porous materials in the grow space.",
        "prevention": "Source clean grain, maintain sterile technique, HEPA filtration, regular deep cleaning of grow space, quarantine new materials.",
        "common_causes": "Contaminated grain from supplier, spores persisting in grow space from previous contamination, inadequate cleaning between grows.",
    },
    {
        "id": "penicillium",
        "common_name": "Blue-Green Mold",
        "scientific_name": "Penicillium spp.",
        "appearance": "Blue-green to teal powdery circular colonies. Similar color to Trichoderma but typically more blue-toned and grows in distinct circular patches rather than rapid spreading.",
        "growth_speed": "Slow to moderate — less aggressive than Trichoderma",
        "smell": "Classic musty, blue cheese-like odor",
        "danger_level": "medium",
        "stages": [
            {
                "name": "Initial spots",
                "description": "Small blue-green circular colonies, often appearing on grain or at substrate edges. White margin around colored center.",
            },
            {
                "name": "Expanding colonies",
                "description": "Colonies expand and deepen in color. Heavy sporulation produces powdery blue-green surface.",
            },
        ],
        "action": "Small isolated spots may be carefully removed with surrounding substrate if caught early. Larger infections should be discarded. Less aggressive than Trichoderma, so isolation and increased FAE can sometimes save a grow.",
        "prevention": "Clean air, proper sterilization, avoid bruising grain during inoculation, maintain good FAE during fruiting.",
        "common_causes": "Airborne spores (extremely common in environments), bruised or damaged grain providing entry point, inadequate sterilization.",
    },
    {
        "id": "wet_spot",
        "common_name": "Wet Spot (Sour Rot)",
        "scientific_name": "Bacillus spp. (endospore-forming bacteria)",
        "appearance": "Uncolonized wet, glassy-looking grain kernels that remain translucent while surrounding grain colonizes normally. Affected grains look waterlogged.",
        "growth_speed": "Does not spread aggressively but affected grains never colonize",
        "smell": "Sour, slightly sweet fermented smell — noticeable when jar is opened or shaken",
        "danger_level": "medium",
        "stages": [
            {
                "name": "Uncolonized wet grain",
                "description": "Individual grains or clusters remain wet and translucent while mycelium colonizes around them. Mycelium visibly avoids these areas.",
            },
            {
                "name": "Sour fermentation",
                "description": "Affected grains develop strong sour smell. May become slightly discolored. Surrounding mycelium growth slows or stalls.",
            },
        ],
        "action": "If less than 10-15% of grain is affected, the jar may still be usable — mycelium will grow around wet spots. If widespread or strongly sour, discard. Never spawn to bulk with heavily affected grain.",
        "prevention": "Proper grain hydration (not too wet), adequate sterilization time and pressure (Bacillus endospores are heat-resistant — need full 15 PSI for 90+ minutes), thorough draining after soak.",
        "common_causes": "Over-hydrated grain, insufficient sterilization time (Bacillus endospores survive short cycles), grain not dried adequately before loading jars.",
    },
]

IDENTIFICATION_SYSTEM_PROMPT = """You are an expert mycologist specializing in contamination identification in mushroom cultivation.

Analyze the uploaded image of a mushroom cultivation substrate, grain jar, agar plate, or fruiting chamber. Your task is to identify any contamination present and assess the overall health of the culture.

Respond ONLY with a JSON object in this exact format:
{
    "contamination_detected": true/false,
    "contaminants": [
        {
            "classification": "trichoderma|cobweb|black_mold|bacterial|lipstick_mold|penicillium|wet_spot|other",
            "confidence": 0.0-1.0,
            "stage": "description of the current stage of contamination",
            "location": "where in the image the contamination is located",
            "action": "keep_monitoring|isolate|discard",
            "reasoning": "detailed explanation of why you identified this contaminant"
        }
    ],
    "health_assessment": "healthy|early_concern|contaminated|severely_contaminated",
    "recommendations": [
        "specific actionable recommendation 1",
        "specific actionable recommendation 2"
    ]
}

Guidelines:
- Be conservative with contamination calls — false positives cause unnecessary discards
- Healthy mycelium (white, rhizomorphic or tomentose) is NORMAL and should not be flagged
- Metabolites (yellow liquid exudate) are NORMAL stress responses, not contamination
- Aerial mycelium (fluffy white growth) is NORMAL, not cobweb mold
- Bruising (blue-green on mushroom tissue) is NORMAL for many species, not mold
- Primordia (small pins) can look unusual but are healthy growth
- If you cannot determine with reasonable confidence, set contamination_detected to false and note your uncertainty in recommendations
- Confidence below 0.5 should use action "keep_monitoring"
- Confidence 0.5-0.75 should use action "isolate"
- Confidence above 0.75 should match the contaminant's danger level for action recommendation
- Always provide at least one recommendation even for healthy cultures"""
