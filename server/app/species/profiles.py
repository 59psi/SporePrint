from .models import GrowPhase, PhaseParams, SpeciesProfile, SubstrateRecipe, TekStep

BUILTIN_PROFILES: list[SpeciesProfile] = [
    # ─── ACTIVE SPECIES ─────────────────────────────────────────────────
    SpeciesProfile(
        id="cubensis_golden_teacher",
        common_name="Golden Teacher / B+",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Golden Teacher",
        substrate_types=["CVG", "manure-based", "BRF"],
        colonization_visual_description=(
            "Dense white rhizomorphic (ropey) mycelium ideal. "
            "Tomentose (fluffy) is normal. Full colonization before fruiting."
        ),
        contamination_risk_notes=(
            "Trich (#1 — white→green 24-48h), cobweb (grey/wispy, fast), "
            "black mold (Aspergillus — discard), bacterial (slimy/sour), "
            "lipstick mold (pink/red — discard)."
        ),
        pinning_trigger_description=(
            "FAE introduction (CO2 drop) + 12/12 light + high surface humidity. "
            "Evaporation from substrate surface is key."
        ),
        phases={
            GrowPhase.AGAR: PhaseParams(
                temp_min_f=75, temp_max_f=80, humidity_min=0, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(7, 14),
                notes="Optional phase. Ambient conditions in SAB/flow hood.",
            ),
            GrowPhase.LIQUID_CULTURE: PhaseParams(
                temp_min_f=75, temp_max_f=80, humidity_min=0, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(10, 21),
                notes="Optional phase. Stir plate recommended.",
            ),
            GrowPhase.GRAIN_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=80, humidity_min=70, humidity_max=100,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(10, 14),
                notes="Optional. In-bag with micropore tape.",
            ),
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=80, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(7, 14),
                notes="Keep dark. No FAE until fully colonized.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=72, temp_max_f=75, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(5, 10),
                notes="Introduce FAE. Surface evaporation triggers pinning.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=72, temp_max_f=76, humidity_min=85, humidity_max=92,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Harvest before spore drop — veil breaking.",
            ),
            GrowPhase.REST: PhaseParams(
                temp_min_f=72, temp_max_f=75, humidity_min=95, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="soaked",
                expected_duration_days=(1, 1),
                notes="Dunk in cold water 12-24h between flushes.",
            ),
        },
        flush_count_typical=4,
        yield_notes="3-5 flushes typical. First flush largest. Expect 1-3oz dry per quart of spawn.",
        tags=["beginner", "fast", "reliable"],
        tldr="Beginner-friendly cubensis baseline. Colonizes CVG or manure substrate in 7-14 days at 75-80°F. Introduce FAE + 12/12 light to pin. 3-5 flushes, first flush is largest. Responds reliably to standard tek. Dunk in cold water between flushes.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "BRF"],
        contamination_risks=["Trichoderma (green mold) — most common threat, appears as white then green patches within 24-48 hours", "Cobweb mold — grey wispy overlay that spreads very fast, often responds to hydrogen peroxide spray", "Bacterial contamination — slimy/sour smell, often from wet spots or poor pasteurization", "Lipstick mold (Sporendonema) — pink/red spots, discard immediately"],
    ),

    SpeciesProfile(
        id="cubensis_penis_envy",
        common_name="Penis Envy (PE)",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Penis Envy",
        substrate_types=["CVG", "enriched manure"],
        colonization_visual_description=(
            "Slower, denser, blobby growth. Overlay common and expected. "
            "Yellow metabolite exudate is NORMAL — not contamination."
        ),
        contamination_risk_notes=(
            "Extended timelines = higher contamination risk. Impeccable technique required. "
            "Same contaminants as GT but longer exposure window."
        ),
        pinning_trigger_description=(
            "Multi-strategy — cold shock (60-65°F for 12-24h), bubble wrap tek, "
            "fork tek for overlay. More stubborn than standard cubensis."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=79, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(14, 21),
                notes="Slower than standard cubensis. Patience required.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=70, temp_max_f=74, humidity_min=92, humidity_max=97,
                co2_max_ppm=700, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(10, 21),
                notes="Aggressive FAE. Consider bubble wrap tek or fork tek for overlay.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=75, humidity_min=88, humidity_max=93,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(14, 21),
                notes="Fruits are dense and heavy. Harvest when caps soften.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Lower yield by count but dense fruits. Fewer but heavier.",
        tags=["intermediate", "advanced", "potent", "slow"],
        tldr="Intermediate-advanced cubensis with slower, denser colonization (14-21 days). Yellow metabolite exudate is normal. Overlay common — use bubble wrap tek or fork tek to break it. Multi-strategy pinning: cold shock, bubble wrap tek, or fork tek. 2-3 flushes of dense heavy fruits. Requires impeccable sterile technique due to extended timeline.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG or enriched manure substrate. PE benefits from nutrient-rich substrates. Pasteurize with boiling water method. PE's slower colonization means substrate must be extremely clean.", duration="8-12 hours", tips=["Enriched manure substrate produces larger, denser PE fruits", "Extra-clean substrate is critical — PE's long colonization gives contaminants more time"], common_mistakes=["Using substrate that is too wet — PE is more sensitive to excess moisture", "Not pasteurizing thoroughly — every shortcut costs you during PE's long colonization"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix with CVG or enriched manure at 1:2 ratio. A higher spawn ratio is recommended for PE to speed colonization and reduce contamination window.", duration="30 minutes", tips=["Use a 1:2 or even 1:1 spawn ratio — faster colonization is critical for PE", "Ensure grain spawn is 100% colonized with no uncolonized kernels"], common_mistakes=["Using too low a spawn ratio — PE's slow colonization needs every advantage", "Using grain spawn that is not fully colonized"]),
            TekStep(step_number=3, title="Extended Colonization", description="Seal the monotub and store in darkness at 75-79°F. PE takes 14-21 days to fully colonize — significantly longer than standard cubensis. Yellow metabolite exudate is NORMAL for PE.", duration="14-21 days", tips=["Yellow metabolite liquid is normal — not contamination", "Be patient — PE takes 2-3x longer than Golden Teacher"], common_mistakes=["Panicking at yellow metabolites and discarding a healthy tub", "Introducing fruiting conditions before full colonization — overlay risk"]),
            TekStep(step_number=4, title="Overlay Management", description="PE commonly develops a thick mycelial overlay (dense mat on surface). If overlay occurs, use bubble wrap tek (lay bubble wrap directly on surface) or fork tek (gently scrape surface with sterilized fork) to break through.", duration="3-7 days for overlay resolution", tips=["Bubble wrap tek: lay bubble side down on surface — creates microclimate", "Fork tek: lightly scratch the surface in a grid pattern with a sterilized fork"], common_mistakes=["Ignoring overlay — pins cannot form through thick overlay mat", "Being too aggressive with fork tek — deep scratches damage the mycelium"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Introduce fruiting conditions: heavy FAE, 12/12 light, 70-75°F. PE fruits are dense and heavy — harvest when caps soften and stems feel slightly squishy. PE caps do not open like standard cubensis.", duration="14-21 days per flush", tips=["PE fruits do not drop veils normally — watch for cap softening as harvest indicator", "Cold shock to 60-65°F for 12-24 hours can help trigger stubborn pins"], common_mistakes=["Waiting for veil break like standard cubensis — PE caps work differently", "Harvesting too early when fruits are still rock-hard"]),
            TekStep(step_number=6, title="Dunk and Subsequent Flushes", description="Soak in cold water 12-24 hours between flushes. PE typically gives 2-3 flushes with decreasing yield. Second flush can be as productive as first if overlay is managed.", duration="12-24 hours soak", tips=["Cold dunk (40-50°F) doubles as cold shock for next flush", "PE fruits are dense — fewer but heavier mushrooms per flush"], common_mistakes=["Giving up after first flush — second flush is often excellent with PE", "Not managing overlay between flushes"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=15, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Higher spawn rate (15%) recommended for PE to speed colonization."),
            SubstrateRecipe(name="Enriched Manure", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=15, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Produces larger individual PE fruits. Higher contamination risk."),
        ],
        substrate_preference_ranking=["CVG", "enriched manure"],
        contamination_risks=["Trichoderma — extended 14-21 day colonization gives trich a much larger window to establish", "Overlay stalling — thick mycelial mat prevents pinning and traps moisture, creating bacterial pockets", "Bacterial blotch — PE's dense, slow-growing mycelium is more susceptible to wet bacterial spots", "Metabolite confusion — yellow exudate is normal for PE but can mask early contamination signs"],
    ),

    SpeciesProfile(
        id="cubensis_ape",
        common_name="Albino Penis Envy (APE)",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Albino Penis Envy",
        substrate_types=["CVG", "enriched manure"],
        colonization_visual_description=(
            "Very slow, dense growth. Even more prone to overlay than PE. "
            "Albino — white fruits, no pigment. Yellow metabolites normal."
        ),
        contamination_risk_notes=(
            "Longest colonization of any cubensis variety. Maximum contamination "
            "exposure window. Sterile technique absolutely critical."
        ),
        pinning_trigger_description=(
            "Same as PE but even more stubborn. Cold shock, bubble wrap tek, fork tek. "
            "May require multiple induction attempts."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=79, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(21, 30),
                notes="Extremely slow. 3-4 weeks minimum.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=70, temp_max_f=74, humidity_min=92, humidity_max=97,
                co2_max_ppm=700, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(14, 28),
                notes="May take 2-4 weeks. Multiple tek strategies may be needed.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=75, humidity_min=88, humidity_max=93,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(14, 21),
                notes="Caps don't open normally. Harvest when caps soften and stems show blue tint.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Lowest yield of cubensis varieties but extremely dense fruits.",
        tags=["advanced", "potent", "slow", "albino"],
        tldr="Advanced cubensis with the longest colonization (21-30 days) and most stubborn pinning of any cubensis variant. Even more overlay-prone than PE. Caps do not open normally — harvest when caps soften and stems show blue tint. Requires multiple induction attempts. Albino appearance; fruits are pure white. 2-3 flushes of extremely dense fruits.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG or enriched manure with meticulous pasteurization. APE has the longest colonization of any cubensis (21-30 days), making substrate cleanliness absolutely paramount.", duration="8-12 hours", tips=["Use CVG for reliability — enriched manure for potentially larger fruits", "Consider pressure-cooking substrate instead of bucket tek for extra sterility"], common_mistakes=["Cutting corners on pasteurization — APE's month-long colonization punishes every shortcut", "Not checking substrate field capacity carefully"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Mix fully colonized grain spawn with substrate at 1:1 to 1:2 ratio. Maximum spawn ratio is strongly recommended for APE to minimize colonization time.", duration="30 minutes", tips=["1:1 spawn ratio is ideal for APE — speed is your best defense against contamination", "Break up grain spawn thoroughly for even distribution"], common_mistakes=["Using low spawn ratios — APE is too slow to tolerate sparse inoculation", "Using grain spawn that is not 100% colonized"]),
            TekStep(step_number=3, title="Extended Colonization", description="Seal tub, store at 75-79°F in darkness. APE takes 21-30 days — the longest of any cubensis. Do not disturb. Yellow metabolites are normal. Full surface colonization required before any attempt at fruiting.", duration="21-30 days", tips=["Set a calendar reminder — resist checking constantly", "Yellow metabolite exudate is completely normal for APE/PE genetics"], common_mistakes=["Opening the tub during colonization out of curiosity", "Mistaking normal slow progress for stalling"]),
            TekStep(step_number=4, title="Pinning Induction (Multi-Strategy)", description="APE is extremely stubborn to pin. Start with standard fruiting conditions (FAE + 12/12 light + 70-74°F). If no pins after 7-10 days, try cold shock (60-65°F for 12-24h). If still no pins, apply bubble wrap tek or fork tek.", duration="14-28 days", tips=["Try each tek sequentially — cold shock first, then bubble wrap, then fork tek", "Multiple attempts may be needed — this is normal for APE"], common_mistakes=["Giving up too early — APE may take 4 weeks to pin", "Applying all teks simultaneously instead of one at a time"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="APE fruits are albino (pure white). Caps do NOT open normally — harvest when caps soften and stems show blue tint. Fruits are extremely dense and heavy despite small appearance.", duration="14-21 days per flush", tips=["Gently squeeze the cap — softening is the harvest signal for APE", "Blue bruising on stems indicates peak maturity"], common_mistakes=["Waiting for caps to open like normal cubensis — they never will", "Harvesting too early when caps are still rock-hard and stems show no blue"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="Cold-water dunk for 12-24 hours. APE typically gives 2-3 flushes. Manage overlay aggressively between flushes.", duration="12-24 hours soak", tips=["Address any overlay before re-introducing fruiting conditions", "Second flush may require another round of cold shock or bubble wrap tek"], common_mistakes=["Expecting more than 2-3 flushes — APE yields are lower count but very dense", "Not re-applying overlay management between flushes"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=20, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Maximum spawn rate (20%) recommended for APE. Speed is critical."),
            SubstrateRecipe(name="Enriched Manure", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=20, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher nutrient content may help with APE's demanding growth. Higher contamination risk."),
        ],
        substrate_preference_ranking=["CVG", "enriched manure"],
        contamination_risks=["Trichoderma — 21-30 day colonization is the highest contamination exposure of any cubensis", "Severe overlay — even more prone than PE; multiple tek strategies often needed", "Bacterial contamination from extended wet conditions during month-long colonization", "Stalling confusion — APE naturally stalls and restarts; distinguishing from contamination stall is difficult"],
    ),

    SpeciesProfile(
        id="cubensis_tidal_wave",
        common_name="Tidal Wave",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Tidal Wave",
        substrate_types=["CVG", "manure-based"],
        colonization_visual_description=(
            "PE x B+ cross. Moderate-fast colonization. Rhizomorphic growth. "
            "Can form 'enigma' blob mutation — dense brain-like masses instead of normal caps."
        ),
        contamination_risk_notes=(
            "Moderate risk similar to standard cubensis. "
            "Enigma form takes longer, increasing contamination window."
        ),
        pinning_trigger_description=(
            "Standard cubensis fruiting conditions. FAE + light + surface evaporation. "
            "Enigma form may require bubble wrap tek."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=80, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(10, 16),
                notes="Faster than PE, slower than GT. Watch for enigma mutation.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=72, temp_max_f=75, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(5, 14),
                notes="Enigma form: dense blob pins. Normal form: standard pins.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=72, temp_max_f=76, humidity_min=85, humidity_max=92,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(10, 21),
                notes="Enigma: harvest when blob stops growing and firms up. Normal: harvest at veil break.",
            ),
        },
        flush_count_typical=3,
        yield_notes="3-4 flushes. Enigma form yields dense masses. Normal form similar to GT.",
        tags=["intermediate", "hybrid", "enigma-possible"],
        tldr="PE x B+ hybrid cubensis with intermediate colonization speed (10-16 days). May spontaneously express the 'enigma' blob mutation — dense brain-like masses instead of normal caps. Standard fruiting conditions apply for normal form; bubble wrap tek helps for enigma form. Enigma form: harvest when blob stops growing and firms up. Normal form: harvest at veil break. 3-4 flushes.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
        ],
        substrate_preference_ranking=["CVG", "manure-based"],
        contamination_risks=["Standard cubensis contamination profile — Trichoderma, cobweb, bacterial", "Enigma mutation form takes longer to mature, increasing contamination window", "Blob/brain structures can trap moisture and harbor bacterial pockets", "Bubble wrap tek for enigma form creates humid microclimate that can encourage bacteria"],
    ),

    SpeciesProfile(
        id="panaeolus_cyanescens",
        common_name="Blue Meanie (Pan Cyan)",
        scientific_name="Panaeolus cyanescens",
        category="active",
        substrate_types=["pasteurized manure", "CVG with manure", "horse dung"],
        colonization_visual_description=(
            "Wispy, light grey-white mycelium. Much less dense than cubensis. "
            "Rhizomorphic growth less pronounced. Colonizes manure-based substrates."
        ),
        contamination_risk_notes=(
            "Manure substrates carry higher contamination risk. Proper pasteurization critical. "
            "Slower colonizer than cubensis — longer exposure window."
        ),
        pinning_trigger_description=(
            "FAE introduction + light + surface evaporation. Casing layer highly recommended. "
            "Pinning is more finicky than cubensis."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=78, temp_max_f=84, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(10, 18),
                notes="Prefers warmer temps than cubensis. Manure-based substrate essential.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=74, temp_max_f=78, humidity_min=92, humidity_max=97,
                co2_max_ppm=700, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(5, 12),
                notes="Casing layer strongly recommended. High surface humidity critical.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=74, temp_max_f=80, humidity_min=88, humidity_max=95,
                co2_max_ppm=700, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Fruits are small, thin-stemmed. Bruise intensely blue. Harvest before caps flatten.",
            ),
        },
        flush_count_typical=3,
        yield_notes="3-5 flushes. Small fruits but highly potent. Lower weight yield than cubensis.",
        tags=["advanced", "potent", "tropical", "manure-substrate"],
        tldr="Advanced species requiring manure-based substrate (not wood/grain). Warmer colonization (78-84°F) than cubensis. Casing layer strongly recommended for pinning. Small thin-stemmed fruits that bruise intensely blue. More finicky to pin than cubensis. 3-5 flushes of highly potent small fruits.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare pasteurized manure-based substrate. Pan cyans REQUIRE manure — they will not fruit on CVG or grain alone. Mix aged horse manure with vermiculite and coco coir. Pasteurize at 160-170°F for 2 hours.", duration="8-12 hours", tips=["Fresh horse manure from an herbivore-only diet is ideal", "Aged manure (composted 2-4 weeks) reduces bacterial load"], common_mistakes=["Trying to use CVG without manure — Pan cyans need the dung nutrients", "Using manure from animals on antibiotics or dewormers"]),
            TekStep(step_number=2, title="Spawn to Substrate with Casing", description="Mix grain spawn with pasteurized manure substrate at 1:3 ratio. Apply a casing layer of peat moss + vermiculite (50/50) on top. Casing layer is highly recommended for Pan cyans.", duration="1 hour", tips=["Casing layer dramatically improves pinning success with this species", "Pasteurize the casing layer separately — microwave moist peat for 5 minutes"], common_mistakes=["Skipping the casing layer — pinning will be unreliable without it", "Making casing layer too thick — 1/4 inch maximum"]),
            TekStep(step_number=3, title="Colonization", description="Seal container at 78-84°F in darkness. Pan cyans prefer warmer colonization than cubensis. Wait for substrate to fully colonize and casing layer to show mycelial threading (10-18 days).", duration="10-18 days", tips=["Warmer temps (80-84°F) speed colonization for this tropical species", "Look for mycelial threads reaching through the casing layer as readiness sign"], common_mistakes=["Colonizing at standard cubensis temps (75°F) — too cool for Pan cyans", "Introducing fruiting before casing is threaded"]),
            TekStep(step_number=4, title="Fruiting Conditions", description="Introduce FAE, 12/12 light, drop temp to 74-78°F. Maintain very high surface humidity (92-97%). Mist casing layer lightly and frequently.", duration="5-12 days to pins", tips=["Surface humidity is critical — tiny droplets on casing, never pooling", "Pan cyans need more humidity than cubensis during pinning"], common_mistakes=["Insufficient humidity — Pan cyans abort pins readily if surface dries", "Heavy direct misting that pools on the casing surface"]),
            TekStep(step_number=5, title="Harvest", description="Fruits are small and thin-stemmed. Bruise intensely blue on handling. Harvest before caps fully flatten — when caps are still slightly convex. Handle gently.", duration="7-14 days per flush", tips=["Handle as little as possible — intense bruising begins immediately", "Use a sharp blade to cut at the base rather than twisting"], common_mistakes=["Waiting for caps to fully flatten — they can split and drop spores quickly", "Rough handling causing excessive bruising"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="Lightly mist casing layer between flushes. No dunk needed — just re-moisten the casing. Pan cyans can produce 3-5 flushes if humidity is maintained.", duration="7-10 days between flushes", tips=["Re-moisten casing gently — do not soak the substrate", "Maintain the same high-humidity environment between flushes"], common_mistakes=["Dunking like cubensis — can waterlog the manure substrate and cause bacterial issues", "Letting the casing layer dry out completely between flushes"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Pasteurized Manure Mix", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "coco coir": "1 quart", "gypsum": "1/2 cup"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="optimal", notes="Manure substrate is required for Pan cyans. Add peat/verm casing layer on top."),
            SubstrateRecipe(name="CVG with Manure Supplement", ingredients={"coco coir": "3 quarts", "aged horse manure": "3 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.85, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Compromise blend — more forgiving than straight manure but still provides dung nutrients."),
        ],
        substrate_preference_ranking=["pasteurized manure", "CVG with manure", "horse dung"],
        contamination_risks=["Bacterial contamination from manure substrate — proper pasteurization is critical", "Longer colonization (10-18 days) at warm temps creates favorable conditions for bacteria", "Pin aborts from humidity fluctuations — Pan cyans are very sensitive to drying", "Competitor molds on improperly pasteurized manure substrate"],
    ),

    SpeciesProfile(
        id="psilocybe_natalensis",
        common_name="Natal Super Strength",
        scientific_name="Psilocybe natalensis",
        category="active",
        substrate_types=["CVG", "manure-based", "pasteurized straw"],
        colonization_visual_description=(
            "Fast, aggressive white mycelium. Rhizomorphic growth similar to cubensis. "
            "Colonizes faster than most cubensis varieties."
        ),
        contamination_risk_notes=(
            "Fast colonizer helps compete. Similar risk profile to cubensis. "
            "Standard sterile technique sufficient."
        ),
        pinning_trigger_description=(
            "FAE introduction + light. Very responsive to standard fruiting conditions. "
            "Easier to pin than PE varieties."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=82, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(7, 12),
                notes="Fast colonizer. Slightly warmer than cubensis preferred.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=72, temp_max_f=76, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(4, 8),
                notes="Pins readily. More forgiving than cubensis PE varieties.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=72, temp_max_f=78, humidity_min=85, humidity_max=92,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Medium-sized fruits. Harvest at veil break.",
            ),
        },
        flush_count_typical=4,
        yield_notes="3-5 flushes. Good yielder. Fruits are medium-sized with notable potency.",
        tags=["intermediate", "fast", "potent", "south-african"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Fast colonizer (7-12 days) from South Africa. Slightly warmer colonization preference (75-82°F) than standard cubensis. Pins more readily than PE varieties. Medium-sized fruits with notable potency. 3-5 flushes of good yield.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "pasteurized straw"],
        contamination_risks=["Standard cubensis contamination profile — Trichoderma, cobweb, bacterial", "Fast colonizer helps compete, making contamination risk lower than most cubensis", "Warmer colonization temps can encourage bacterial growth if substrate is too wet", "Standard sterile technique sufficient — lower risk than PE/APE varieties"],
    ),

    SpeciesProfile(
        id="psilocybe_tampanensis",
        common_name="Philosopher's Stone",
        scientific_name="Psilocybe tampanensis",
        category="active",
        substrate_types=["rye grain", "brown rice flour", "wild bird seed"],
        colonization_visual_description=(
            "Wispy white mycelium. Produces sclerotia (truffles) — dense nuggets that form "
            "within the grain substrate. Sclerotia are the primary harvest, not mushrooms."
        ),
        contamination_risk_notes=(
            "Long sclerotia formation period increases risk. "
            "Sealed jars reduce exposure. Sterile grain prep critical."
        ),
        pinning_trigger_description=(
            "For sclerotia: NO fruiting trigger needed — they form in sealed jars during colonization. "
            "For mushrooms (optional): standard FAE + light after sclerotia harvest."
        ),
        phases={
            GrowPhase.GRAIN_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=82, humidity_min=0, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(60, 120),
                notes="Sclerotia form in sealed jars over 2-4 months. No opening, no FAE. "
                      "Patience is the entire technique.",
            ),
        },
        flush_count_typical=0,
        yield_notes="Harvest is sclerotia (truffles) from inside the jar. 50-100g fresh per quart jar typical.",
        tags=["intermediate", "sclerotia", "truffles", "long-cycle"],
        tldr="Sclerotia-producing species grown in sealed jars on grain — no fruiting trigger needed. Sclerotia (truffles) form over 2-4 months in the sealed jar during colonization. No opening, no FAE, no intervention. Patience is the entire technique. 50-100g fresh per quart jar typical. Optional: can also fruit small mushrooms on CVG after sclerotia harvest.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tek_guide=[
            TekStep(step_number=1, title="Grain Preparation", description="Prepare rye grain or wild bird seed in quart jars. Simmer grain until hydrated but not split. Load into jars with micropore tape lids. Pressure sterilize at 15 PSI for 90 minutes.", duration="3-4 hours", tips=["Rye grain produces the most consistent sclerotia", "Dry grain surface before loading jars — excess surface moisture causes bacterial issues"], common_mistakes=["Over-cooking grain until it splits — mushy grain breeds bacteria", "Not sterilizing long enough — grain is nutrient-rich and needs full 90 minutes"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate cooled grain jars with liquid culture or agar wedge using sterile technique. Shake jar gently to distribute inoculant. Seal and store in darkness.", duration="30 minutes", tips=["Liquid culture gives more even distribution than spore syringe", "Work in a SAB or flow hood — sterile technique is critical for the long cycle ahead"], common_mistakes=["Using multi-spore syringe — takes much longer to colonize than LC", "Opening jars in non-sterile environment"]),
            TekStep(step_number=3, title="Colonization and Sclerotia Formation", description="Store sealed jars at 75-82°F in complete darkness. Do NOT open, shake, or disturb jars for 2-4 months. Sclerotia (truffles) form as dense nuggets within the grain substrate during this period.", duration="60-120 days", tips=["Set a calendar date 3-4 months out and genuinely forget about the jars", "Sclerotia form better in slightly warmer conditions (78-82°F)"], common_mistakes=["Opening jars to check — the entire tek relies on leaving them sealed", "Shaking jars after colonization has started — disrupts sclerotia formation"]),
            TekStep(step_number=4, title="Harvest Sclerotia", description="After 2-4 months, open jars and sift through grain to collect sclerotia (dense brown-tan nuggets). Rinse gently, pat dry. Fresh sclerotia can be consumed immediately or dried.", duration="1 hour", tips=["Longer incubation (4+ months) produces larger sclerotia", "Sclerotia should feel dense and firm — soft ones are immature"], common_mistakes=["Harvesting too early — less than 2 months produces tiny, sparse sclerotia", "Not drying properly for storage — fresh sclerotia spoil quickly"]),
            TekStep(step_number=5, title="Optional Mushroom Fruiting", description="After sclerotia harvest, remaining colonized grain can be cased with CVG and introduced to standard fruiting conditions for small mushroom production.", duration="14-28 days", tips=["Mushroom fruiting is a bonus — sclerotia are the primary harvest", "Use a thin CVG casing layer over the spent grain"], common_mistakes=["Expecting large mushroom yields — fruiting after sclerotia harvest is low-yield", "Skipping the casing layer — tampanensis needs it for mushroom pinning"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Rye Grain (Sclerotia Production)", ingredients={"whole rye grain": "1 quart", "water": "as needed for hydration", "gypsum": "1 tablespoon"}, water_liters_per_liter_substrate=0.5, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="optimal", notes="Rye grain produces the best sclerotia. Hydrate grain by simmering, NOT soaking."),
            SubstrateRecipe(name="Wild Bird Seed", ingredients={"wild bird seed": "1 quart", "water": "as needed", "gypsum": "1 tablespoon"}, water_liters_per_liter_substrate=0.5, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="good", notes="Cheaper alternative to rye. Slightly smaller sclerotia."),
        ],
        substrate_preference_ranking=["rye grain", "brown rice flour", "wild bird seed"],
        contamination_risks=["Green mold (Trichoderma) — long 2-4 month sealed cycle means any initial contamination has time to take over", "Bacterial contamination from improperly sterilized grain", "Wet rot if grain is over-hydrated before sterilization", "Cannot be inspected during growth — contamination discovered only at harvest"],
    ),

    SpeciesProfile(
        id="psilocybe_mexicana",
        common_name="Psilocybe mexicana",
        scientific_name="Psilocybe mexicana",
        category="active",
        substrate_types=["rye grain", "brown rice flour", "wild bird seed"],
        colonization_visual_description=(
            "Wispy white mycelium similar to tampanensis. Produces sclerotia (truffles) in grain. "
            "Can also fruit small mushrooms on CVG if desired."
        ),
        contamination_risk_notes=(
            "Same risk profile as tampanensis. Long cycle in sealed jars. "
            "Sterile grain prep is the critical step."
        ),
        pinning_trigger_description=(
            "For sclerotia: sealed jars, no intervention. "
            "For mushrooms: case with CVG, introduce FAE + light."
        ),
        phases={
            GrowPhase.GRAIN_COLONIZATION: PhaseParams(
                temp_min_f=72, temp_max_f=80, humidity_min=0, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(60, 90),
                notes="Sclerotia production in sealed jars. 2-3 months. "
                      "Slightly faster than tampanensis.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=76, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(10, 21),
                notes="Optional fruiting phase. Small mushrooms on cased substrate.",
            ),
        },
        flush_count_typical=0,
        yield_notes="Primary harvest is sclerotia. Optional small mushroom fruiting from cased substrate.",
        tags=["intermediate", "sclerotia", "truffles", "historic"],
        tldr="Sclerotia-producing species grown in sealed jars on rye grain or BRF. Sclerotia form over 2-3 months in the sealed jar — slightly faster than tampanensis. No intervention needed. Optional: case with CVG and introduce FAE + light for small mushroom fruiting. Historic species with Mazatec ceremonial significance.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tek_guide=[
            TekStep(step_number=1, title="Grain Preparation", description="Prepare rye grain in quart jars. Same grain prep as tampanensis — simmer until hydrated, load jars, pressure sterilize at 15 PSI for 90 minutes.", duration="3-4 hours", tips=["Rye grain is the gold standard for sclerotia species", "Ensure grain surface is dry before jarring to prevent bacteria"], common_mistakes=["Over-hydrating grain — leads to bacterial contamination", "Insufficient sterilization time"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate with liquid culture or agar wedge in sterile conditions. P. mexicana colonizes slightly faster than tampanensis.", duration="30 minutes", tips=["Liquid culture is preferred over multi-spore for even colonization", "Work in front of a flow hood or inside a SAB"], common_mistakes=["Using non-sterile technique — contamination will ruin the 2-3 month investment", "Not flame-sterilizing between jars"]),
            TekStep(step_number=3, title="Sclerotia Formation", description="Store sealed jars at 72-80°F in darkness for 2-3 months. P. mexicana is slightly faster than tampanensis. Do not open or disturb jars.", duration="60-90 days", tips=["P. mexicana sclerotia form slightly faster than tampanensis (2-3 vs 2-4 months)", "Warmer temps within range speed sclerotia development"], common_mistakes=["Opening jars before 2 months minimum", "Storing at fluctuating temperatures"]),
            TekStep(step_number=4, title="Harvest Sclerotia", description="Open jars and collect sclerotia nuggets from within the grain. Rinse, pat dry. Can be consumed fresh or dried for storage.", duration="1 hour", tips=["P. mexicana sclerotia are generally smaller but more numerous than tampanensis", "Historic species — used in Mazatec ceremonies for centuries"], common_mistakes=["Harvesting before 2 months — patience is key", "Not properly drying for storage"]),
            TekStep(step_number=5, title="Optional Mushroom Fruiting", description="Case spent grain with CVG, introduce FAE and light. P. mexicana can produce small mushrooms on cased substrate.", duration="10-21 days", tips=["Small but distinctive mushrooms with conical caps", "Casing layer required for fruiting"], common_mistakes=["Expecting large mushroom yields from a sclerotia species", "Skipping casing layer"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Rye Grain (Sclerotia Production)", ingredients={"whole rye grain": "1 quart", "water": "as needed for hydration", "gypsum": "1 tablespoon"}, water_liters_per_liter_substrate=0.5, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="optimal", notes="Standard sclerotia grain prep. Slightly faster production than tampanensis."),
        ],
        substrate_preference_ranking=["rye grain", "brown rice flour", "wild bird seed"],
        contamination_risks=["Green mold during long sealed incubation — same risk profile as tampanensis", "Bacterial contamination from improperly sterilized grain", "Cannot inspect during growth — contamination only visible at harvest", "Wet rot from over-hydrated grain"],
    ),

    SpeciesProfile(
        id="psilocybe_azurescens",
        common_name="Azurescens / Flying Saucer",
        scientific_name="Psilocybe azurescens",
        category="active",
        substrate_types=["hardwood chips (alder)", "hardwood sawdust", "cardboard"],
        colonization_visual_description=(
            "White mycelium, moderate speed. Wood-loving species — colonizes wood chips, "
            "not grain/CVG like cubensis. Rhizomorphic growth on wood substrates."
        ),
        contamination_risk_notes=(
            "Wood-chip substrate outdoors is standard but indoor cultivation possible. "
            "Non-sterile substrates mean competitor molds are common."
        ),
        pinning_trigger_description=(
            "Cold shock required — needs sustained cold temps (40-55°F) to fruit. "
            "Naturally fruits in Pacific Northwest autumn. Indoor cold room or refrigerator fruiting."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=60, temp_max_f=75, humidity_min=80, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(60, 120),
                notes="Wood-lover. Colonizes alder/hardwood chips. Very slow — 2-4 months. "
                      "Outdoor bed cultivation is traditional.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=40, temp_max_f=55, humidity_min=95, humidity_max=100,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(14, 28),
                notes="Needs COLD temperatures. Naturally fruits in PNW autumn (40-55°F). "
                      "Requires cold room or outdoor fruiting.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=40, temp_max_f=58, humidity_min=90, humidity_max=100,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(14, 21),
                notes="Very cold fruiter. Caramel-brown caps. Among the most potent psilocybin species.",
            ),
        },
        flush_count_typical=1,
        yield_notes="1-2 flushes. Low yield but extremely potent (up to 1.8% psilocybin). "
                    "Wood-chip bed can produce for multiple seasons outdoors.",
        tags=["advanced", "wood-lover", "cold-fruiting", "potent", "outdoor-capable"],
        tldr="Outdoor cold-weather wood-lover — not practical for indoor cultivation without a cold room. Colonizes alder/hardwood chips over 2-4 months. Requires sustained cold (40-55°F) to fruit — naturally fruits in Pacific Northwest autumn. Caramel-brown caps. Low yield but among the most potent psilocybin species documented. Wood-chip bed can produce for multiple seasons.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tek_guide=[
            TekStep(step_number=1, title="Wood Chip Bed Preparation", description="Prepare outdoor bed with fresh alder or hardwood chips. Clear a 4x4 foot area in a shaded location. Soak wood chips in water for 24-48 hours, then drain.", duration="2-3 days", tips=["Alder chips are the traditional and preferred substrate", "Choose a shaded north-facing location protected from direct sun and wind"], common_mistakes=["Using dry wood chips without soaking — mycelium needs moisture", "Choosing a location with full sun exposure — azurescens needs shade"]),
            TekStep(step_number=2, title="Layered Bed Inoculation", description="Layer soaked wood chips with grain spawn in the prepared bed: 2-inch chips, thin spawn layer, 2-inch chips, spawn, 2-inch chips on top. Cover with cardboard and mulch.", duration="2-3 hours", tips=["Cardboard cover retains moisture and protects mycelium", "Water bed thoroughly after assembly"], common_mistakes=["Not using enough spawn — azurescens is slow and needs good starting coverage", "Forgetting the cardboard cover — beds dry out without it"]),
            TekStep(step_number=3, title="Colonization (Extended)", description="Allow the bed to colonize for 2-4 months minimum. Keep moist with occasional watering. Mycelium will colonize throughout the wood chips. This is an outdoor, low-maintenance phase.", duration="60-120 days", tips=["Check moisture monthly — water like a garden bed during dry spells", "White mycelium visible on chip edges indicates healthy colonization"], common_mistakes=["Letting the bed dry out completely during summer", "Disturbing the bed to check colonization"]),
            TekStep(step_number=4, title="Cold-Triggered Fruiting", description="Azurescens naturally fruits in autumn when temperatures drop to 40-55°F. In Pacific Northwest climates, this happens October-December. Indoor cold rooms can simulate these conditions.", duration="14-28 days", tips=["Patience through summer — fruiting only occurs with sustained cold", "Multiple seasons of fruiting are possible from established beds"], common_mistakes=["Expecting fruits in the first season — may take until second autumn", "Trying to force fruiting with inadequate cold temperatures"]),
            TekStep(step_number=5, title="Harvest and Bed Maintenance", description="Harvest mushrooms when caps are still slightly convex. Leave the bed intact — it can produce for multiple years with annual topdressing of fresh wood chips.", duration="Annual maintenance", tips=["Add 1-2 inches of fresh wood chips each spring to feed the mycelium", "Established beds are perennial and improve with age"], common_mistakes=["Destroying the bed after first harvest — beds produce for years", "Not topdressing with fresh chips — mycelium exhausts the substrate"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Alder Wood Chips (Outdoor Bed)", ingredients={"fresh alder wood chips": "5 cubic feet", "cardboard": "4x4 foot sheet", "mulch": "2 inches"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=10, sterilization_method="pasteurize_cold_lime", sterilization_time_min=0, sterilization_temp_f=None, suitability="optimal", notes="Outdoor beds are the traditional and most reliable method. No sterilization needed — outdoor microbial environment is part of the ecology."),
            SubstrateRecipe(name="Hardwood Sawdust (Indoor Attempt)", ingredients={"hardwood sawdust (alder/birch)": "5 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=15, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="acceptable", notes="Indoor cultivation is experimental and unreliable. Requires sustained cold room at 40-55°F for fruiting."),
        ],
        substrate_preference_ranking=["hardwood chips (alder)", "hardwood sawdust", "cardboard"],
        contamination_risks=["Competitor molds on outdoor beds — green mold, black mold from neighboring decomposers", "Slugs and insects consuming fruits — common pest issue in outdoor beds", "Drying out during summer months — kills mycelium if bed goes fully dry", "Indoor attempts have high failure rate — azurescens strongly prefers outdoor ecology"],
    ),

    SpeciesProfile(
        id="psilocybe_zapotecorum",
        common_name="Zapotec Mushroom",
        scientific_name="Psilocybe zapotecorum",
        category="active",
        substrate_types=["CVG", "manure-based", "enriched hardwood"],
        colonization_visual_description=(
            "White mycelium, moderate speed. Subtropical species from Mexico. "
            "Less documented cultivation than cubensis but growing in popularity."
        ),
        contamination_risk_notes=(
            "Similar risk profile to cubensis. Warm-loving species. "
            "Standard sterile technique applies."
        ),
        pinning_trigger_description=(
            "FAE introduction + light + humidity increase. "
            "Similar triggers to cubensis but prefers warmer conditions."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=82, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(14, 21),
                notes="Subtropical species. Prefers warm colonization.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=72, temp_max_f=78, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Standard fruiting conditions. Responds to FAE + light.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=78, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(10, 18),
                notes="Highest psilocybin content documented (1.89% — Windsor et al. 2026). "
                      "Tall, slender fruits.",
            ),
        },
        flush_count_typical=3,
        yield_notes="2-4 flushes. Moderate yield. Highest documented psilocybin content of any cultivated species.",
        tags=["advanced", "potent", "tropical", "research-documented"],
        tldr="Subtropical Mexican species with 14-21 day colonization at warmer temps (75-82°F). Standard FAE + light fruiting trigger. Tall slender fruits. 2-4 flushes of moderate yield. Documented at 1.89% psilocybin content (Windsor et al. 2026) — the highest of any cultivated species on record.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "enriched hardwood"],
        contamination_risks=["Standard cubensis contamination profile — Trichoderma, cobweb, bacterial", "Warmer colonization temps (75-82°F) can encourage bacterial growth on wet substrate", "Less documented cultivation than cubensis — fewer troubleshooting resources available", "Subtropical species may struggle in cold/dry climates"],
    ),

    # ─── GOURMET SPECIES ────────────────────────────────────────────────
    SpeciesProfile(
        id="pearl_oyster",
        common_name="Pearl / Grey Oyster",
        scientific_name="Pleurotus ostreatus",
        category="gourmet",
        substrate_types=["straw", "hardwood sawdust", "masters mix", "coffee grounds", "cardboard"],
        colonization_visual_description=(
            "Very fast, aggressive white mycelium. The most forgiving oyster species. "
            "Will colonize almost anything cellulose-based."
        ),
        contamination_risk_notes=(
            "Extremely fast colonizer — best beginner species. Very competitive against contaminants. "
            "Can succeed even on imperfectly pasteurized substrate."
        ),
        pinning_trigger_description=(
            "Temperature drop + FAE. Extremely responsive. "
            "Will often pin in bag before you're ready."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(7, 14),
                notes="In-bag with filter patch. Very fast colonizer. Will fruit on almost anything.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=50, temp_max_f=60, humidity_min=90, humidity_max=95,
                co2_max_ppm=500, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(3, 5),
                notes="Cold shock triggers massive pinning. Very responsive.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=70, humidity_min=85, humidity_max=92,
                co2_max_ppm=700, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(5, 7),
                notes="Widest temp range of any oyster. Harvest before caps flatten/edges upturn.",
            ),
        },
        flush_count_typical=3,
        yield_notes="3-4 flushes. Highest yielder of all oysters. The #1 beginner species worldwide.",
        tags=["beginner", "fast", "forgiving", "high-yield", "versatile-substrate"],
        tldr="The classic oyster — most versatile and forgiving species. Grows on nearly anything cellulose-based. Wide fruiting range (55-75°F). 3-5 prolific flushes. Perfect first mushroom for any beginner.",
        flavor_profile="Mild, slightly sweet with a delicate velvety texture. Versatile in cooking — sautés, soups, pasta, stir-fries. Absorbs flavors well.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Chop straw into 2-4 inch pieces (or use hardwood pellets). Pasteurize using hot water bath at 160-170°F for 60-90 minutes, or use cold water lime bath for 18-24 hours. Drain and cool to room temperature.", duration="4-24 hours depending on method", tips=["Hot water pasteurization is faster; cold lime bath is simpler and uses no fuel", "Straw should be damp like a wrung-out sponge, not dripping"], common_mistakes=["Under-pasteurizing — remaining contaminants will outcompete the mycelium", "Not draining thoroughly — excess water pools at the bottom and breeds bacteria"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Layer or mix grain spawn with cooled pasteurized straw inside grow bags (with filter patch) or 5-gallon buckets (with holes drilled). Target 10% spawn rate. Pack firmly but not overly tight.", duration="30-60 minutes", tips=["5-gallon buckets with 1/2-inch holes every 6 inches are cheap and effective", "Pack substrate firmly to eliminate air pockets"], common_mistakes=["Too little spawn — slow colonization invites contamination", "Not packing firmly enough — air gaps create dry spots that do not colonize"]),
            TekStep(step_number=3, title="Colonization", description="Store bags or buckets in a dark location at the species-appropriate temperature. Colonization takes 10-14 days for most oyster species. White mycelium should fully cover all substrate.", duration="10-14 days", tips=["Slight warmth speeds colonization — oysters are aggressive colonizers", "Small amounts of condensation inside bags is normal"], common_mistakes=["Storing in a location with wide temperature swings", "Not waiting for full colonization — patches of uncolonized straw are contamination entry points"]),
            TekStep(step_number=4, title="Fruiting Initiation", description="Cut X-shaped slits or holes in bags (or buckets already have holes). Move to a well-ventilated space with indirect light. Introduce temperature drop if required by species. Mist 2-3x daily.", duration="3-7 days to first pins", tips=["Pins form at the holes/slits where fresh air meets the colonized substrate", "A simple fan on a timer provides consistent FAE"], common_mistakes=["Insufficient ventilation — oysters are very CO2-sensitive", "Placing in direct sunlight — indirect light is sufficient"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Mushroom clusters grow rapidly from the openings. Harvest when cap edges begin to flatten or just before they upturn. Twist and pull the entire cluster or cut at the base.", duration="5-7 days per flush", tips=["Harvest the entire cluster at once rather than individual mushrooms", "Harvest before caps fully flatten to maximize shelf life and reduce spore load"], common_mistakes=["Waiting too long — caps upturn, spore load increases, flesh becomes tough", "Pulling too hard and tearing substrate from the holes"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="After harvest, continue misting and maintaining FAE. Next flush typically appears in 7-14 days. Most oyster species produce 3-4 flushes from straw substrates.", duration="7-14 days between flushes", tips=["Soak the block/bucket for a few hours between flushes if it feels light and dry", "Yield decreases with each subsequent flush — first flush is always the largest"], common_mistakes=["Stopping care after first flush — oysters are reliable multi-flushers", "Over-soaking between flushes — 2-4 hour soak is sufficient, not 24 hours"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Pasteurized Straw", ingredients={"chopped wheat/oat straw": "5 lbs", "water": "as needed"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="The classic oyster substrate. Cheap, readily available, excellent yields."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
        ],
        substrate_preference_ranking=["straw", "masters mix", "hardwood sawdust", "coffee grounds", "cardboard"],
        contamination_risks=["Trichoderma (green mold) on poorly pasteurized straw — the most common issue", "Bacterial blotch from over-wet substrate or poor drainage", "Spore load at maturity — heavy spore drop can trigger respiratory sensitivity", "Fruit fly infestation in warm conditions — use fine mesh over openings"],
    ),

    SpeciesProfile(
        id="phoenix_oyster",
        common_name="Phoenix / Italian Oyster",
        scientific_name="Pleurotus pulmonarius",
        category="gourmet",
        substrate_types=["straw", "hardwood sawdust", "masters mix"],
        colonization_visual_description=(
            "Fast aggressive white mycelium. Very similar to pearl oyster but "
            "prefers warmer fruiting temperatures."
        ),
        contamination_risk_notes=(
            "Fast colonizer, resistant to contamination. Same risk profile as pearl oyster."
        ),
        pinning_trigger_description=(
            "FAE introduction + light. Less cold shock needed than blue/pearl oyster — "
            "warm-weather fruiter."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=70, temp_max_f=80, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(8, 14),
                notes="In-bag. Fast colonizer like other oysters.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=65, temp_max_f=80, humidity_min=85, humidity_max=92,
                co2_max_ppm=700, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(5, 7),
                notes="Warm-weather oyster. Ideal when closet runs too warm for blue/pearl.",
            ),
        },
        flush_count_typical=3,
        yield_notes="3-4 flushes. Good yield. Better summer performance than blue/pearl oyster.",
        tags=["beginner", "warm", "fast", "summer-grower"],
        tldr="Warm-weather oyster variant. Fruits at higher temps (65-80°F) than Blue/Pearl. Good for summer growing. Otherwise similar cultivation to Pearl Oyster.",
        flavor_profile="Similar to Pearl Oyster but slightly more robust flavor. Good all-purpose culinary mushroom.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Chop straw into 2-4 inch pieces (or use hardwood pellets). Pasteurize using hot water bath at 160-170°F for 60-90 minutes, or use cold water lime bath for 18-24 hours. Drain and cool to room temperature.", duration="4-24 hours depending on method", tips=["Hot water pasteurization is faster; cold lime bath is simpler and uses no fuel", "Straw should be damp like a wrung-out sponge, not dripping"], common_mistakes=["Under-pasteurizing — remaining contaminants will outcompete the mycelium", "Not draining thoroughly — excess water pools at the bottom and breeds bacteria"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Layer or mix grain spawn with cooled pasteurized straw inside grow bags (with filter patch) or 5-gallon buckets (with holes drilled). Target 10% spawn rate. Pack firmly but not overly tight.", duration="30-60 minutes", tips=["5-gallon buckets with 1/2-inch holes every 6 inches are cheap and effective", "Pack substrate firmly to eliminate air pockets"], common_mistakes=["Too little spawn — slow colonization invites contamination", "Not packing firmly enough — air gaps create dry spots that do not colonize"]),
            TekStep(step_number=3, title="Colonization", description="Store bags or buckets in a dark location at the species-appropriate temperature. Colonization takes 10-14 days for most oyster species. White mycelium should fully cover all substrate.", duration="10-14 days", tips=["Slight warmth speeds colonization — oysters are aggressive colonizers", "Small amounts of condensation inside bags is normal"], common_mistakes=["Storing in a location with wide temperature swings", "Not waiting for full colonization — patches of uncolonized straw are contamination entry points"]),
            TekStep(step_number=4, title="Fruiting Initiation", description="Cut X-shaped slits or holes in bags (or buckets already have holes). Move to a well-ventilated space with indirect light. Introduce temperature drop if required by species. Mist 2-3x daily.", duration="3-7 days to first pins", tips=["Pins form at the holes/slits where fresh air meets the colonized substrate", "A simple fan on a timer provides consistent FAE"], common_mistakes=["Insufficient ventilation — oysters are very CO2-sensitive", "Placing in direct sunlight — indirect light is sufficient"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Mushroom clusters grow rapidly from the openings. Harvest when cap edges begin to flatten or just before they upturn. Twist and pull the entire cluster or cut at the base.", duration="5-7 days per flush", tips=["Harvest the entire cluster at once rather than individual mushrooms", "Harvest before caps fully flatten to maximize shelf life and reduce spore load"], common_mistakes=["Waiting too long — caps upturn, spore load increases, flesh becomes tough", "Pulling too hard and tearing substrate from the holes"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="After harvest, continue misting and maintaining FAE. Next flush typically appears in 7-14 days. Most oyster species produce 3-4 flushes from straw substrates.", duration="7-14 days between flushes", tips=["Soak the block/bucket for a few hours between flushes if it feels light and dry", "Yield decreases with each subsequent flush — first flush is always the largest"], common_mistakes=["Stopping care after first flush — oysters are reliable multi-flushers", "Over-soaking between flushes — 2-4 hour soak is sufficient, not 24 hours"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Pasteurized Straw", ingredients={"chopped wheat/oat straw": "5 lbs", "water": "as needed"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="The classic oyster substrate. Cheap, readily available, excellent yields."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["straw", "hardwood sawdust", "masters mix"],
        contamination_risks=["Bacterial contamination favored by warm, humid conditions this species prefers", "Trichoderma on under-pasteurized straw", "Fruit fly attraction in warm growing environments", "Spore load at maturity — similar to other oysters"],
    ),

    SpeciesProfile(
        id="blue_oyster",
        common_name="Blue Oyster",
        scientific_name="Pleurotus columbinus",
        category="gourmet",
        substrate_types=["straw", "hardwood sawdust", "masters mix"],
        colonization_visual_description=(
            "Aggressive white mycelium. Colonizes fast. "
            "May pin in bag — cut and fruit immediately if so."
        ),
        contamination_risk_notes=(
            "Fast colonizer, relatively resistant. Main risk is green mold (Trichoderma) "
            "on poorly pasteurized substrate."
        ),
        pinning_trigger_description=(
            "Cold shock (drop to 50-55°F) + massive FAE increase. "
            "Very responsive to temperature drop."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(10, 14),
                notes="In-bag with filter patch. Fast colonizer.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=50, temp_max_f=55, humidity_min=90, humidity_max=95,
                co2_max_ppm=500, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(3, 5),
                notes="COLD SHOCK required. Aggressive FAE. CO2 must be <500ppm.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=65, humidity_min=85, humidity_max=92,
                co2_max_ppm=700, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(5, 7),
                notes="CRITICAL: >700ppm CO2 = etiolation (leggy stems, tiny caps). Heavy spore load near maturity.",
            ),
        },
        flush_count_typical=3,
        yield_notes="3-4 flushes. High yielder. First flush is largest by far.",
        tags=["beginner", "fast", "cold-tolerant", "high-yield"],
        tldr="Cold-weather beginner favorite. Colonizes fast (10-14 days) on cheap substrates like straw. Fruits at 55-65°F with heavy FAE. Very CO2 sensitive — >700ppm causes leggy stems. 3-4 flushes, 1-2 lbs per 5lb block. Cut Xs in bag to fruit.",
        flavor_profile="Mild, slightly earthy with subtle anise notes. Firm meaty texture. Excellent sautéed in butter or in stir-fries. Holds up well in soups and stews.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Chop straw to 2-4 inch pieces or use hardwood pellets. Pasteurize via hot water bath (160-170°F for 90 min) or cold lime soak (18-24 hours). Drain thoroughly — blue oyster is sensitive to waterlogged substrate.", duration="4-24 hours", tips=["Straw is the cheapest and most effective substrate for blue oyster", "Drain straw for 2-4 hours after pasteurization to reach proper moisture"], common_mistakes=["Leaving substrate too wet — blue oyster pins best on well-drained substrate", "Using sawdust without supplementation — straw is far simpler for this species"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Layer grain spawn with cooled straw in filter-patch bags or 5-gallon buckets with drilled holes. 10% spawn rate. Pack firmly.", duration="30-60 minutes", tips=["5-gallon bucket tek with 1/2-inch holes is ideal for blue oyster", "Firm packing eliminates dry spots"], common_mistakes=["Loose packing creating air gaps", "Too little spawn — blue oyster colonizes fast but needs good starting coverage"]),
            TekStep(step_number=3, title="Colonization", description="Store at 68-75°F in darkness for 10-14 days. Blue oyster colonizes aggressively. If you see pins forming in the bag before full colonization, proceed to fruiting immediately.", duration="10-14 days", tips=["Blue oyster often pins in the bag — this is a sign to start fruiting right away", "Colonization at the warmer end of range (72-75°F) speeds things up"], common_mistakes=["Ignoring pins forming in the bag — they will abort if conditions are not changed", "Waiting too long after full colonization"]),
            TekStep(step_number=4, title="Cold Shock and Fruiting", description="CRITICAL: Blue oyster requires a cold shock to 50-55°F for pinning. Move to a cold area with massive FAE. CO2 must be under 500ppm during pinning and under 700ppm during fruiting. This species is EXTREMELY CO2-sensitive.", duration="3-5 days to pins", tips=["A garage, basement, or outdoor area in cool weather works for the cold shock", "CO2 is the #1 factor — more FAE is almost always better with blue oyster"], common_mistakes=["Insufficient cold shock — needs sustained 50-55°F, not a brief chill", "CRITICAL: CO2 above 700ppm causes etiolation — long leggy stems with tiny caps"]),
            TekStep(step_number=5, title="Harvest", description="Harvest when cap edges flatten or just begin to upturn. Blue oyster drops very heavy spore loads — harvest before caps fully upturn to reduce spores in the grow area.", duration="5-7 days per flush", tips=["Harvest entire clusters at once by twisting at the base", "Heavy spore load warning — harvest promptly or use respiratory protection"], common_mistakes=["Waiting until caps fully upturn — massive spore release, respiratory irritant", "Not wearing a mask if harvesting overripe clusters"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="Continue misting and FAE. Blue oyster typically gives 3-4 flushes. Brief soak between flushes if substrate feels dry.", duration="7-14 days between flushes", tips=["First flush is by far the largest — expect diminishing returns", "Maintain cold temperatures and heavy FAE throughout"], common_mistakes=["Letting temperature rise above 65°F during fruiting — causes elongation", "Reducing FAE after first flush"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Pasteurized Straw", ingredients={"chopped wheat/oat straw": "5 lbs", "water": "as needed"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="The classic oyster substrate. Cheap, readily available, excellent yields."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
        ],
        substrate_preference_ranking=["straw", "hardwood sawdust", "masters mix"],
        contamination_risks=["Etiolation from elevated CO2 (>700ppm) — appears as long stems and tiny caps, not a contamination but a critical environmental issue", "Trichoderma on poorly pasteurized straw", "Heavy spore load at maturity — respiratory irritant, must harvest promptly", "Bacterial blotch from waterlogged substrate"],
    ),

    SpeciesProfile(
        id="pink_oyster",
        common_name="Pink Oyster",
        scientific_name="Pleurotus djamor",
        category="gourmet",
        substrate_types=["straw", "hardwood sawdust", "masters mix"],
        colonization_visual_description=(
            "Very fast, aggressive white mycelium. Pink coloring appears at fruiting only."
        ),
        contamination_risk_notes=(
            "Fast colonizer. Main risk is bacterial contamination in warm, humid conditions."
        ),
        pinning_trigger_description=(
            "No cold shock needed — tropical species. Just introduce FAE and light."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=85, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(7, 10),
                notes="Tropical species. Loves warmth.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=85, humidity_min=85, humidity_max=95,
                co2_max_ppm=700, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(5, 7),
                notes="CRITICAL: Dies below 40°F. Cannot be refrigerated. Process immediately post-harvest.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Moderate yield. Must be eaten/dried immediately — no refrigeration.",
        tags=["beginner", "tropical", "warm", "fast"],
        tldr="Tropical beginner species. Fast colonizer at 75-85°F. CANNOT be refrigerated (dies below 40°F). Short shelf life (1-2 days post-harvest). Beautiful vibrant pink color fades when cooked. 2-3 flushes.",
        flavor_profile="Delicate with a slight seafood/bacon-like flavor when seared. Color fades to tan when cooked. Best harvested young. Quick cook methods preferred.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Pasteurize straw or hardwood pellets. Pink oyster thrives on inexpensive substrates. Standard hot water pasteurization at 160-170°F for 90 minutes.", duration="4-12 hours", tips=["Pink oyster grows fast on any cellulose substrate — straw is cheapest", "Works well on cardboard, paper, even coffee grounds in a pinch"], common_mistakes=["Over-thinking substrate — pink oyster is the most forgiving species", "Not draining excess water — bacteria thrive in warm, wet conditions"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Mix grain spawn with cooled substrate in bags or buckets at 10% spawn rate. Pink oyster colonizes extremely fast — often visible growth within 24 hours.", duration="30 minutes", tips=["Even 5% spawn rate works — this species is incredibly aggressive", "Room temperature mixing is fine — no need for extra warmth"], common_mistakes=["Using too much spawn — wasteful given pink oyster's aggressive colonization", "Not having fruiting space ready — colonization is very fast"]),
            TekStep(step_number=3, title="Colonization", description="Store at 75-85°F in darkness. Pink oyster is the fastest colonizer in the library — full colonization in 7-10 days. It will begin to fruit even before you are ready.", duration="7-10 days", tips=["Pink oyster loves warmth — the warmer (within range), the faster", "Have your fruiting space set up before colonization finishes"], common_mistakes=["Storing at cold temperatures — pink oyster is a tropical species that hates cold", "CRITICAL: Never refrigerate pink oyster mycelium or spawn — it dies below 40°F"]),
            TekStep(step_number=4, title="Fruiting (No Cold Shock)", description="No cold shock needed — tropical species. Simply introduce FAE and light. Pink oyster pins very readily. Maintain high humidity (85-95%).", duration="5-7 days per flush", tips=["No cold shock needed — just FAE and light", "Mist heavily — tropical species loves humidity"], common_mistakes=["Attempting cold shock — KILLS pink oyster", "Insufficient humidity — causes dry, cracked caps"]),
            TekStep(step_number=5, title="Harvest and IMMEDIATE Processing", description="CRITICAL: Pink oyster CANNOT be refrigerated. Harvest and process (cook, dry, or eat) within hours. Vibrant pink color fades when cooked. Shelf life is 1-2 days maximum at room temperature.", duration="Same day as harvest", tips=["Dehydrate immediately at 135°F if not eating fresh", "Vibrant pink color fades to tan when cooked — this is normal"], common_mistakes=["CRITICAL: Putting harvested pink oyster in the refrigerator — it will die and rot rapidly", "Not having a plan for the harvest — you cannot store this mushroom"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Pasteurized Straw", ingredients={"chopped wheat/oat straw": "5 lbs", "water": "as needed"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="The classic oyster substrate. Cheap, readily available, excellent yields."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["straw", "hardwood sawdust", "masters mix"],
        contamination_risks=["Bacterial contamination from warm, humid growing conditions", "CRITICAL: Pink oyster dies below 40°F — never refrigerate spawn, mycelium, or harvested fruits", "Fruit fly infestation — warm growing temps attract flies", "Short post-harvest shelf life (1-2 days) — process immediately or mushrooms rot"],
    ),

    SpeciesProfile(
        id="king_trumpet",
        common_name="King Trumpet",
        scientific_name="Pleurotus eryngii",
        category="gourmet",
        substrate_types=["masters mix", "supplemented hardwood"],
        colonization_visual_description=(
            "Moderate speed. Dense white mycelium. Full colonization critical before fruiting."
        ),
        contamination_risk_notes=(
            "Moderate risk. Longer colonization than other oysters increases exposure window."
        ),
        pinning_trigger_description=(
            "Cold shock + ELEVATED CO2 during primordia (opposite of other oysters). "
            "Fewer but larger individual fruits."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 21),
                notes="In-bag with filter patch. Slower than other oysters.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=50, temp_max_f=55, humidity_min=90, humidity_max=95,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=4, light_hours_off=20, light_spectrum="daylight_6500k",
                light_lux_target=200,
                fae_mode="passive", expected_duration_days=(5, 7),
                notes="UNIQUE: Wants ELEVATED CO2 (1000-2000ppm) during primordia. Restrict FAE intentionally.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=58, temp_max_f=65, humidity_min=80, humidity_max=90,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Fewer but larger fruits. Thick meaty stems are the prize.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Lower count but large individual fruits with thick stems.",
        tags=["intermediate", "cold-tolerant", "unique-co2"],
        tldr="Intermediate. Thick meaty stems are the prize. UNIQUE: wants elevated CO2 (1000-2000ppm) during primordia — opposite of other oysters. Sterilized (not pasteurized) substrate required. Excellent 7-10 day shelf life. 1-2 flushes.",
        flavor_profile="Rich umami, meaty flavor. Thick dense stems with scallop-like texture when sliced and seared. Best king oyster prep: slice stems into 1-inch coins, sear in hot oil until golden. One of the best culinary mushrooms.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare Masters Mix (50/50 hardwood pellets and soy hull pellets) or supplemented hardwood sawdust. King trumpet REQUIRES pressure sterilization — pasteurization is insufficient for supplemented substrates.", duration="4-6 hours", tips=["Masters Mix is the industry standard for king trumpet", "Hydrate pellets with measured water (1.2L per liter substrate) before sterilizing"], common_mistakes=["Trying to pasteurize instead of pressure sterilize — supplemented substrates MUST be sterilized", "Not using supplemented substrate — plain straw/sawdust gives poor king trumpet yields"]),
            TekStep(step_number=2, title="Inoculation and Bagging", description="Load hydrated, sterilized substrate into filter-patch bags in front of a flow hood. Inoculate with grain spawn at 10% rate. Seal bags and mix gently.", duration="1-2 hours", tips=["Flow hood or SAB is essential — king trumpet is less aggressive than oysters", "Gently mix spawn throughout the bag for even colonization"], common_mistakes=["Working outside a clean air environment — king trumpet is more contamination-prone than oysters", "Packing bags too tight — some air space is needed"]),
            TekStep(step_number=3, title="Colonization", description="Incubate bags at 68-75°F in darkness for 14-21 days. King trumpet colonizes more slowly than other oysters. Full colonization is critical before fruiting.", duration="14-21 days", tips=["King trumpet is slower than blue/pink oyster — patience is needed", "Do not proceed to fruiting until bags are fully colonized"], common_mistakes=["Fruiting before full colonization — leads to contamination", "Storing at warm temperatures above 75°F"]),
            TekStep(step_number=4, title="Primordia with ELEVATED CO2", description="UNIQUE: King trumpet wants elevated CO2 (1000-2000ppm) during primordia — the OPPOSITE of other oysters. Cold shock to 50-55°F and RESTRICT FAE intentionally. This produces fewer but much larger fruits.", duration="5-7 days", tips=["This is the opposite of every other oyster — restrict FAE during pinning", "Cold shock is still needed, but keep ventilation minimal"], common_mistakes=["CRITICAL: Providing heavy FAE like other oysters — this produces many tiny worthless fruits", "Not cold-shocking — king trumpet still needs the temperature drop"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="After primordia form, gradually increase FAE and raise temp to 58-65°F. King trumpet fruits are thick-stemmed — the meaty stem is the prize. Harvest when caps begin to flatten.", duration="7-14 days", tips=["The thick stem is the culinary prize — unlike other oysters where caps are preferred", "Fewer but larger fruits = better outcome for king trumpet"], common_mistakes=["Expecting cluster morphology like other oysters — king trumpet grows individual stalks", "Harvesting when stems are still thin — let them thicken fully"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="King trumpet typically gives 2-3 flushes. Rest block briefly between flushes, re-soak if dry. Later flushes produce progressively smaller stems.", duration="7-14 days between flushes", tips=["King trumpet has excellent shelf life (7-10 days refrigerated)", "Even smaller second-flush fruits have excellent flavor"], common_mistakes=["Expecting many flushes like other oysters — 2-3 is typical", "Not adjusting CO2 strategy for each flush"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
        ],
        substrate_preference_ranking=["masters mix", "supplemented hardwood"],
        contamination_risks=["Trichoderma — longer colonization (14-21 days) means more exposure than fast oysters", "Green mold from improperly sterilized supplemented substrate", "Bacterial contamination if substrate is too wet during restricted-FAE primordia phase", "Contamination during the elevated-CO2 pinning phase — reduced FAE means less drying action"],
    ),

    SpeciesProfile(
        id="lions_mane",
        common_name="Lion's Mane",
        scientific_name="Hericium erinaceus",
        category="gourmet",
        substrate_types=["supplemented hardwood", "masters mix"],
        colonization_visual_description=(
            "Mycelium noticeably finer and less opaque than other species — this is NORMAL, "
            "not contamination. Premature pinning in bags is common."
        ),
        contamination_risk_notes=(
            "Moderate risk. Fine mycelium can be mistaken for contamination. "
            "Slower colonizer than oysters."
        ),
        pinning_trigger_description=(
            "Temperature swing (6-10°F daily fluctuation) + heavy FAE + low CO2. "
            "Unique temp swing requirement."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=77, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 21),
                notes="In-bag with filter patch. Fine mycelium is normal for this species.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=55, temp_max_f=65,
                temp_swing_required=True, temp_swing_delta_f=8.0,
                humidity_min=90, humidity_max=95,
                co2_max_ppm=500, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                light_lux_target=300,
                fae_mode="continuous", expected_duration_days=(5, 10),
                notes="CRITICAL: Requires 6-10°F daily temp swing (e.g. 58°F night / 66°F day). Heavy FAE.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=68, humidity_min=85, humidity_max=95,
                co2_max_ppm=600, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(7, 14),
                notes="CO2 >600ppm → coral/branching deformities instead of pom-pom. Vision should detect.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Single large pom-pom fruit body per opening. Harvest before teeth yellow.",
        tags=["intermediate", "medicinal", "nootropic", "temp-swing"],
        tldr="Intermediate. CRITICAL: very CO2 sensitive (<600ppm) — insufficient FAE causes coral/branching instead of pom-pom shape. Requires 6-10°F daily temp swings for pinning. Fine wispy mycelium is NORMAL (not weak). Premature pinning common. 2-3 flushes, 1-1.5 lbs per 5lb block.",
        flavor_profile="Lobster/crab-like flavor and texture. Tear into pieces and sear in butter until golden — remarkably similar to seafood. Also excellent as a steak substitute. Mild when raw, rich when cooked. Brain health superfood.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust (80% hardwood, 20% wheat bran) or Masters Mix. Pressure sterilize at 15 PSI for 2.5 hours. Lion's mane requires sterilized substrate.", duration="4-6 hours", tips=["Oak and beech sawdust are preferred hardwoods for lion's mane", "Masters Mix produces slightly higher yields than plain supplemented sawdust"], common_mistakes=["Using straw — lion's mane performs poorly on pasteurized straw", "Insufficient sterilization time — supplemented substrates need the full 150 minutes"]),
            TekStep(step_number=2, title="Inoculation", description="Load sterilized substrate into filter-patch bags in front of a flow hood. Inoculate with grain spawn at 10% rate. Lion's mane mycelium is noticeably finer and less opaque than other species — this is NORMAL.", duration="1-2 hours", tips=["Lion's mane mycelium looks thin and wispy — do not mistake this for weak growth", "Use a flow hood — lion's mane is less aggressive than oysters against contaminants"], common_mistakes=["Mistaking normal fine mycelium for contamination or weak growth", "Working without clean air — lion's mane needs good sterile technique"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 68-77°F in darkness for 14-21 days. Lion's mane often begins to fruit prematurely in the bag — small teeth formations poking through filter patches are common.", duration="14-21 days", tips=["Premature pinning in bags is very common — not a problem, just proceed to fruiting", "Full colonization produces better yields, but do not panic at early pins"], common_mistakes=["Panicking at premature pinning — it is extremely common with lion's mane", "Storing at temperatures above 77°F"]),
            TekStep(step_number=4, title="Fruiting with Temperature Swings", description="CRITICAL: Lion's mane requires 6-10°F daily temperature swings for pinning. Example: 58°F at night, 66°F during the day. Heavy FAE is essential — CO2 must be below 500ppm during pinning and 600ppm during fruiting. Elevated CO2 causes coral/branching deformities instead of the desired pom-pom shape.", duration="5-10 days to first pins", tips=["Program a temperature controller for day/night cycling — this is not optional", "More FAE is almost always better — lion's mane is even more CO2-sensitive than blue oyster"], common_mistakes=["CRITICAL: Not providing temperature swings — static temperature often fails to trigger pins", "CRITICAL: CO2 above 600ppm causes coral morphology instead of pom-pom — increase FAE aggressively"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="A single pom-pom fruit body forms at each opening. Harvest when teeth are 1/4 to 1/2 inch long and before they begin to yellow. The fruit body should be white and fluffy.", duration="7-14 days per flush", tips=["Harvest before teeth yellow — yellowing indicates over-maturity", "Single large pom-pom per opening is normal — not clusters like oysters"], common_mistakes=["Waiting until teeth are very long and yellowing — texture and flavor decline", "Expecting cluster morphology — lion's mane forms single globular fruits"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="2-3 flushes typical. Soak block briefly between flushes. Second flush pom-poms are usually smaller. Maintain temperature swings and heavy FAE throughout.", duration="10-14 days between flushes", tips=["Continue temperature swings for subsequent flushes", "Lion's mane has short shelf life — process within 3-5 days of harvest"], common_mistakes=["Stopping temperature swings after first flush", "Storing harvested lion's mane too long — it yellows and degrades quickly"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "masters mix"],
        contamination_risks=["Coral/branching deformity from elevated CO2 — not a contamination but a critical environmental issue", "Trichoderma during the 14-21 day colonization period", "Premature pinning can weaken the block and reduce overall yield", "Fine mycelium is easily outcompeted by aggressive contaminants if sterile technique is poor"],
    ),

    SpeciesProfile(
        id="shiitake",
        common_name="Shiitake",
        scientific_name="Lentinula edodes",
        category="gourmet",
        substrate_types=["supplemented hardwood (oak)", "logs"],
        colonization_visual_description=(
            "White mycelium, moderate speed. After colonization, blocks develop brown outer skin "
            "(browning/popcorning). NOT ready to fruit until browning completes."
        ),
        contamination_risk_notes=(
            "Long colonization (30-60d) increases risk. Green mold main threat. "
            "Browning phase is protective once complete."
        ),
        pinning_trigger_description=(
            "Cold-water soak (35-50°F, 12-24h) after browning complete. "
            "Manual intervention — system reminds and logs."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=77, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(30, 60),
                notes="Very long colonization. 4-8 weeks. Patience critical.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=50, temp_max_f=60, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(5, 10),
                notes="Cold-water soak (35-50°F, 12-24h) initiates pinning. Browning must be complete first.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=50, temp_max_f=65, humidity_min=80, humidity_max=90,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="blue_emphasis",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Blue-shifted light improves cap color. Harvest before caps flatten.",
            ),
        },
        flush_count_typical=4,
        yield_notes="3-6 flushes from blocks. Cold-water soak between flushes. Logs can produce for years.",
        tags=["intermediate", "slow", "long-cycle", "browning-phase"],
        tldr="Intermediate. LONG colonization (30-60 days). Unique browning phase — block develops brown skin that MUST complete before fruiting. Cold shock (38-50°F overnight) triggers pinning. Remove entire bag for fruiting. Soak between flushes. 3-5 flushes over months. Avoid Masters Mix.",
        flavor_profile="Rich, smoky, deeply savory umami. Meaty texture. The world's second most cultivated mushroom. Incredible dried (concentrates flavor). Essential in Asian cuisine — soups, stir-fries, ramen, dashi.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust (oak preferred, 80% sawdust, 20% wheat bran). Hydrate and pressure sterilize at 15 PSI for 2.5 hours. Alternatively, inoculate hardwood logs with plug spawn.", duration="4-6 hours (blocks) or 2-3 hours (logs)", tips=["Oak sawdust is the gold standard for shiitake blocks", "For log cultivation, use freshly-cut hardwood logs 3-6 inches diameter, cut 2-4 weeks before inoculation"], common_mistakes=["Using Masters Mix — shiitake performs better on straight supplemented hardwood", "Using logs from conifers — shiitake requires hardwood"]),
            TekStep(step_number=2, title="Inoculation", description="For blocks: load sterilized substrate into filter-patch bags, inoculate with grain spawn at 10% rate in front of flow hood. For logs: drill holes every 6 inches, insert plug spawn, seal with cheese wax.", duration="1-3 hours", tips=["Block cultivation produces first fruits faster (3-4 months vs 6-12 months for logs)", "For logs, drill holes in a diamond pattern for even colonization"], common_mistakes=["Not sealing log plug holes with wax — dries out and invites contamination", "Skipping flow hood for block inoculation — shiitake's long cycle demands sterility"]),
            TekStep(step_number=3, title="Extended Colonization", description="Incubate blocks at 68-77°F for 30-60 DAYS. This is the longest colonization of any common gourmet species. Do not disturb. Full colonization is absolutely mandatory.", duration="30-60 days", tips=["Shiitake colonization takes 4-8 weeks — set a reminder and be patient", "For logs: stack in shaded outdoor area, keep moist, wait 6-12 months"], common_mistakes=["Fruiting before complete colonization — guaranteed contamination", "Not waiting the full 30-60 days — partial colonization is unacceptable"]),
            TekStep(step_number=4, title="Browning Phase", description="UNIQUE TO SHIITAKE: After colonization, blocks develop a brown outer skin (browning/popcorning). This protective layer MUST complete before fruiting. Remove bag completely and let block sit in indirect light with moderate humidity for 7-14 days.", duration="7-14 days", tips=["The brown skin is a protective barrier — it means the block is ready", "Popcorn-like bumps on the brown surface are the completion indicator"], common_mistakes=["CRITICAL: Trying to fruit before browning completes — the brown skin is essential", "Keeping blocks in bags during browning — they need air exposure"]),
            TekStep(step_number=5, title="Cold-Water Soak Trigger", description="UNIQUE: Shiitake pinning is triggered by cold-water soaking. Submerge the browned block in cold water (35-50°F) for 12-24 hours. Remove, drain, and place in fruiting chamber.", duration="12-24 hours soak + 5-10 days to pins", tips=["The colder the water, the more effective the trigger — use ice water if possible", "Weight down the block to keep it submerged — it will float"], common_mistakes=["Using warm or room-temperature water — the COLD is the trigger", "Not soaking long enough — full 12-24 hours is needed"]),
            TekStep(step_number=6, title="Fruiting and Harvest", description="Maintain 50-65°F with moderate FAE and 12/12 light with blue emphasis. Harvest when caps are 70-80% open — edges still slightly curled down. Soak again between flushes.", duration="7-14 days per flush", tips=["Blue-shifted light improves cap color and thickness", "Shiitake blocks can produce 3-6 flushes with cold-water soak between each"], common_mistakes=["Waiting until caps fully flatten — tough texture and reduced flavor", "Not soaking between flushes — the cold-water soak is needed for EACH flush"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
            SubstrateRecipe(name="Hardwood Log Cultivation", ingredients={"fresh hardwood log (oak/maple)": "3-6 inch diameter x 3-4 feet", "plug spawn": "30-50 plugs per log", "cheese wax": "as needed to seal holes"}, water_liters_per_liter_substrate=0.0, spawn_rate_percent=5, sterilization_method="pasteurize_hot_water", sterilization_time_min=0, sterilization_temp_f=None, suitability="good", notes="Log cultivation takes 6-12 months to first fruit but can produce for 3-5+ years."),
        ],
        substrate_preference_ranking=["supplemented hardwood (oak)", "logs"],
        contamination_risks=["Trichoderma (green mold) — 30-60 day colonization is a long exposure window", "Green mold during the browning phase if blocks are kept too wet", "Bacterial contamination from improper cold-water soak — change water if reusing", "Competitor molds on outdoor logs — slugs and insects can introduce contamination"],
    ),

    SpeciesProfile(
        id="yellow_oyster",
        common_name="Yellow Oyster",
        scientific_name="Pleurotus citrinopileatus",
        category="gourmet",
        substrate_types=["straw", "hardwood sawdust", "masters mix"],
        colonization_visual_description=(
            "Very fast, aggressive white mycelium. Similar to pink oyster. "
            "Bright yellow caps at fruiting."
        ),
        contamination_risk_notes=(
            "Fast colonizer, relatively resistant. Tropical species — "
            "bacterial contamination risk in warm humid conditions."
        ),
        pinning_trigger_description=(
            "No cold shock needed — tropical species. FAE + light triggers pinning. "
            "Very easy to fruit."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=70, temp_max_f=80, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(8, 12),
                notes="Tropical species. Fast colonizer.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=64, temp_max_f=78, humidity_min=85, humidity_max=95,
                co2_max_ppm=700, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(5, 7),
                notes="Wider temp range than pink oyster. Bright yellow color fades when overripe.",
            ),
        },
        flush_count_typical=3,
        yield_notes="3-4 flushes. Moderate yield. Delicate flavor — best fresh, doesn't dry well.",
        tags=["beginner", "tropical", "fast", "colorful"],
        tldr="Warm-weather beginner strain. Colonizes at 70-80°F, fruits at 64-78°F. Aggressive colonizer. Bright yellow clusters. Slightly bitter if undercooked. 2-3 flushes.",
        flavor_profile="Nutty, cashew-like flavor. Slightly bitter raw — must be thoroughly cooked. Delicate texture. Beautiful garnish when raw (for color only).",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Chop straw into 2-4 inch pieces (or use hardwood pellets). Pasteurize using hot water bath at 160-170°F for 60-90 minutes, or use cold water lime bath for 18-24 hours. Drain and cool to room temperature.", duration="4-24 hours depending on method", tips=["Hot water pasteurization is faster; cold lime bath is simpler and uses no fuel", "Straw should be damp like a wrung-out sponge, not dripping"], common_mistakes=["Under-pasteurizing — remaining contaminants will outcompete the mycelium", "Not draining thoroughly — excess water pools at the bottom and breeds bacteria"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Layer or mix grain spawn with cooled pasteurized straw inside grow bags (with filter patch) or 5-gallon buckets (with holes drilled). Target 10% spawn rate. Pack firmly but not overly tight.", duration="30-60 minutes", tips=["5-gallon buckets with 1/2-inch holes every 6 inches are cheap and effective", "Pack substrate firmly to eliminate air pockets"], common_mistakes=["Too little spawn — slow colonization invites contamination", "Not packing firmly enough — air gaps create dry spots that do not colonize"]),
            TekStep(step_number=3, title="Colonization", description="Store bags or buckets in a dark location at the species-appropriate temperature. Colonization takes 10-14 days for most oyster species. White mycelium should fully cover all substrate.", duration="10-14 days", tips=["Slight warmth speeds colonization — oysters are aggressive colonizers", "Small amounts of condensation inside bags is normal"], common_mistakes=["Storing in a location with wide temperature swings", "Not waiting for full colonization — patches of uncolonized straw are contamination entry points"]),
            TekStep(step_number=4, title="Fruiting Initiation", description="Cut X-shaped slits or holes in bags (or buckets already have holes). Move to a well-ventilated space with indirect light. Introduce temperature drop if required by species. Mist 2-3x daily.", duration="3-7 days to first pins", tips=["Pins form at the holes/slits where fresh air meets the colonized substrate", "A simple fan on a timer provides consistent FAE"], common_mistakes=["Insufficient ventilation — oysters are very CO2-sensitive", "Placing in direct sunlight — indirect light is sufficient"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Mushroom clusters grow rapidly from the openings. Harvest when cap edges begin to flatten or just before they upturn. Twist and pull the entire cluster or cut at the base.", duration="5-7 days per flush", tips=["Harvest the entire cluster at once rather than individual mushrooms", "Harvest before caps fully flatten to maximize shelf life and reduce spore load"], common_mistakes=["Waiting too long — caps upturn, spore load increases, flesh becomes tough", "Pulling too hard and tearing substrate from the holes"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="After harvest, continue misting and maintaining FAE. Next flush typically appears in 7-14 days. Most oyster species produce 3-4 flushes from straw substrates.", duration="7-14 days between flushes", tips=["Soak the block/bucket for a few hours between flushes if it feels light and dry", "Yield decreases with each subsequent flush — first flush is always the largest"], common_mistakes=["Stopping care after first flush — oysters are reliable multi-flushers", "Over-soaking between flushes — 2-4 hour soak is sufficient, not 24 hours"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Pasteurized Straw", ingredients={"chopped wheat/oat straw": "5 lbs", "water": "as needed"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="The classic oyster substrate. Cheap, readily available, excellent yields."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["straw", "hardwood sawdust", "masters mix"],
        contamination_risks=["Bacterial contamination from warm, humid tropical conditions", "Trichoderma on poorly pasteurized substrate", "Fruit fly infestation in warm growing environment", "Short shelf life — does not dry well, must be used fresh or quickly"],
    ),

    SpeciesProfile(
        id="chestnut",
        common_name="Chestnut",
        scientific_name="Pholiota adiposa",
        category="gourmet",
        substrate_types=["supplemented hardwood", "masters mix"],
        colonization_visual_description=(
            "White mycelium, moderate speed. Dense colonization pattern. "
            "Small brown-capped mushrooms with slight crackle pattern on cap."
        ),
        contamination_risk_notes=(
            "Moderate risk. Slower colonizer than oysters. "
            "Supplemented substrate increases contamination risk."
        ),
        pinning_trigger_description=(
            "Cool temperatures + FAE + light. Benefits from slight cold shock. "
            "Pins from block surface or through holes in bags."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 21),
                notes="In-bag with filter patch. Moderate colonization speed.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=50, temp_max_f=60, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(5, 10),
                notes="Benefits from cold shock. High humidity critical.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=65, humidity_min=85, humidity_max=92,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Harvest in clusters when caps are still slightly convex.",
            ),
        },
        flush_count_typical=3,
        yield_notes="2-4 flushes. Small dense mushrooms. Nutty flavor. Popular in Asian cuisine.",
        tags=["intermediate", "cold-tolerant", "nutty"],
        tldr="Beginner-Intermediate. Reliable colonizer on supplemented sawdust. Fruits at 55-65°F. Beautiful brown caps. Great shelf life. 2-3 flushes.",
        flavor_profile="Rich nutty flavor true to its name. Firm texture. Versatile — sautés, roasts, soups. Deeper flavor than oysters.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust or Masters Mix. Pressure sterilize at 15 PSI for 2.5 hours.", duration="4-6 hours", tips=["Oak or beech sawdust works best for chestnut mushrooms", "Masters Mix produces reliable results"], common_mistakes=["Using straw — chestnut performs poorly on unsterlized substrates", "Insufficient sterilization time"]),
            TekStep(step_number=2, title="Inoculation", description="Load sterilized substrate into filter-patch bags in front of flow hood. Inoculate with grain spawn at 10% rate.", duration="1-2 hours", tips=["Use a flow hood — chestnut is slower than oysters and needs good sterile technique", "Mix spawn evenly throughout the bag"], common_mistakes=["Working outside clean air environment", "Uneven spawn distribution creating colonization gaps"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 65-75°F in darkness for 14-21 days. Chestnut colonizes at moderate speed.", duration="14-21 days", tips=["Full colonization is required before fruiting", "Moderate speed — slower than oysters but faster than shiitake"], common_mistakes=["Fruiting before full colonization", "Storing at temperatures above 75°F"]),
            TekStep(step_number=4, title="Fruiting Initiation", description="Cold shock to 50-60°F. Cut holes in bags or remove block from bag. Introduce FAE and 12/12 light. High humidity (90-95%) is critical during pinning.", duration="5-10 days to pins", tips=["Cold shock triggers dense pinning", "High humidity during pinning is critical for chestnut"], common_mistakes=["Insufficient cold shock — needs a genuine temperature drop", "Low humidity during pinning phase"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain 55-65°F with moderate FAE. Harvest in clusters when caps are still slightly convex — before they flatten.", duration="7-14 days per flush", tips=["Harvest while caps are still convex for best flavor and texture", "Small brown caps with crackle pattern are characteristic"], common_mistakes=["Waiting until caps fully flatten — texture becomes tough", "Breaking apart clusters — harvest entire cluster"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="2-3 flushes typical. Brief soak between flushes. Maintain cool temperatures.", duration="7-14 days between flushes", tips=["Good shelf life compared to oysters", "Nutty flavor intensifies in later flushes"], common_mistakes=["Letting block dry out between flushes", "Raising temperature above fruiting range"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "masters mix"],
        contamination_risks=["Trichoderma from slow colonization on supplemented substrate", "Bacterial contamination at high humidity levels", "Green mold if sterilization is insufficient", "Competitor molds on damaged or cracked substrate blocks"],
    ),

    SpeciesProfile(
        id="pioppino",
        common_name="Pioppino / Black Poplar",
        scientific_name="Cyclocybe aegerita",
        category="gourmet",
        substrate_types=["supplemented hardwood", "masters mix", "straw with supplements"],
        colonization_visual_description=(
            "White mycelium, moderate speed. Can form thick mat. "
            "Fruits in attractive clusters with long thin stems and small dark caps."
        ),
        contamination_risk_notes=(
            "Moderate risk. Longer colonization than oysters. "
            "Good competitor once established."
        ),
        pinning_trigger_description=(
            "Temperature drop + FAE + light. Remove from bag and expose top surface. "
            "Fruits from top of block."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(21, 35),
                notes="Slow-moderate colonizer. Full colonization before fruiting.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=50, temp_max_f=60, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(5, 10),
                notes="Cold shock beneficial. Remove block from bag, expose top surface.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=68, humidity_min=85, humidity_max=92,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(10, 18),
                notes="Harvest clusters when caps begin to flatten. Meaty texture, holds shape when cooked.",
            ),
        },
        flush_count_typical=3,
        yield_notes="2-4 flushes. Moderate yield. Premium gourmet — excellent texture and flavor.",
        tags=["intermediate", "slow", "premium-gourmet", "italian"],
        tldr="Intermediate. 21-30 day colonization. Cold fruiter (55-65°F). Dense clusters with long crunchy stems. One of the best culinary mushrooms. 2-3 flushes.",
        flavor_profile="Nutty, peppery, with an exceptional crunchy stem texture that holds up to any cooking method. Sometimes called 'swordbelt mushroom.' Highly prized by chefs. Excellent shelf life.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust or Masters Mix. Pressure sterilize at 15 PSI for 2.5 hours.", duration="4-6 hours", tips=["Oak sawdust with wheat bran supplementation is ideal", "Masters Mix also works well"], common_mistakes=["Using pasteurized straw without supplementation", "Insufficient sterilization"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized substrate in filter-patch bags with grain spawn at 10% rate in front of flow hood.", duration="1-2 hours", tips=["Even spawn distribution is important for pioppino", "Flow hood required — pioppino is a moderate-speed colonizer"], common_mistakes=["Working in non-sterile conditions", "Uneven spawn placement"]),
            TekStep(step_number=3, title="Extended Colonization", description="Incubate at 65-75°F in darkness for 21-35 days. Pioppino is a slow-moderate colonizer. Full colonization is essential.", duration="21-35 days", tips=["Be patient — pioppino is slower than oysters but worth the wait", "Full colonization produces better yields"], common_mistakes=["Rushing to fruiting before full colonization", "Fluctuating temperatures during colonization"]),
            TekStep(step_number=4, title="Top-Fruiting Setup", description="Cold shock to 50-60°F. Remove block from bag, exposing the top surface. Pioppino fruits from the top — set up in a humidity tent or chamber with top exposed.", duration="5-10 days to pins", tips=["Top-fruiting is the standard approach for pioppino", "A humidity tent over the block works well"], common_mistakes=["Trying to fruit through bag holes like oysters — pioppino prefers top-fruiting", "Insufficient humidity during pinning"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain 55-68°F with moderate FAE. Harvest clusters when caps begin to flatten. Pioppino has exceptional long crunchy stems — the stems are the culinary prize.", duration="10-18 days per flush", tips=["The crunchy stem texture is pioppino's best feature — harvest to preserve it", "Harvest the full cluster before caps fully flatten"], common_mistakes=["Harvesting too early when stems are still thin", "Waiting until caps are fully flat — stems become hollow"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="2-3 flushes typical. Brief soak between flushes. Excellent shelf life.", duration="10-14 days between flushes", tips=["Pioppino has excellent shelf life — one of the best among gourmet species", "Subsequent flushes produce smaller but equally flavorful clusters"], common_mistakes=["Not re-soaking blocks between flushes", "Expecting many flushes — 2-3 is typical"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "masters mix", "straw with supplements"],
        contamination_risks=["Trichoderma from the 21-35 day colonization window", "Bacterial contamination on exposed top-fruiting surfaces", "Green mold if sterilization of supplemented substrate is inadequate", "Competitor molds during the long colonization phase"],
    ),

    SpeciesProfile(
        id="nameko",
        common_name="Nameko",
        scientific_name="Pholiota nameko",
        category="gourmet",
        substrate_types=["supplemented hardwood", "hardwood sawdust", "logs"],
        colonization_visual_description=(
            "White mycelium, moderate speed. Distinctive orange-brown caps "
            "with thick gelatinous coating (slime layer)."
        ),
        contamination_risk_notes=(
            "Moderate risk. Requires very high humidity during fruiting — "
            "creates conditions favorable to bacterial contamination."
        ),
        pinning_trigger_description=(
            "Cold shock + very high humidity (95%+). Fruits in dense clusters. "
            "Slime layer is normal and desirable."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 28),
                notes="In-bag with filter patch. Moderate speed.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=45, temp_max_f=55, humidity_min=95, humidity_max=100,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(5, 10),
                notes="Needs cold shock AND very high humidity. Slime layer appears at pinning.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=50, temp_max_f=60, humidity_min=90, humidity_max=98,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="VERY high humidity required. Harvest when caps are still rounded with slime intact.",
            ),
        },
        flush_count_typical=3,
        yield_notes="2-4 flushes. Moderate yield. Prized for soups — gelatinous texture is the feature.",
        tags=["intermediate", "cold-tolerant", "high-humidity", "japanese"],
        tldr="Intermediate. Cold fruiter (50-60°F). Requires VERY high humidity (90-100%) for the signature gelatinous coating. Cut most of top off bag, leave 4-inch walls. Prized in Japanese cuisine. 2-3 flushes.",
        flavor_profile="Mild, slightly nutty with a distinctive slippery/gelatinous texture. The amber gelatin coating is the prized feature. Essential in Japanese miso soup and nabemono hot pots.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust. Pressure sterilize at 15 PSI for 2.5 hours. Nameko requires high-quality substrate.", duration="4-6 hours", tips=["Beech or oak sawdust is preferred for nameko", "Supplementation with wheat bran at 20% is standard"], common_mistakes=["Using straw — nameko requires supplemented hardwood", "Insufficient sterilization"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized bags with grain spawn at 10% rate using flow hood.", duration="1-2 hours", tips=["Nameko is moderately aggressive — standard sterile technique is sufficient", "Even spawn distribution helps"], common_mistakes=["Contamination from poor sterile technique", "Over-packing bags"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 65-75°F in darkness for 14-28 days. Moderate colonization speed.", duration="14-28 days", tips=["Full colonization required before cold-shocking", "Moderate speed — be patient"], common_mistakes=["Premature fruiting", "Temperature fluctuations"]),
            TekStep(step_number=4, title="Cold Shock Pinning", description="Cold shock to 45-55°F with very high humidity (95-100%). Nameko requires exceptionally high humidity — higher than any other common gourmet species. The signature gelatinous slime layer appears at pinning.", duration="5-10 days to pins", tips=["95-100% humidity is not optional — the slime layer needs it", "The gelatinous coating is the prized feature, not a defect"], common_mistakes=["Insufficient humidity — nameko without slime is nameko without value", "Not cold-shocking enough — needs genuine cold, not just cool"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain 50-60°F with 90-98% humidity. Harvest when caps are still rounded with slime coating intact. Clusters of small amber mushrooms.", duration="7-14 days per flush", tips=["Handle gently to preserve the slime coating", "Best harvested and used fresh for the gelatinous texture"], common_mistakes=["Letting humidity drop below 90% — slime dries and caps crack", "Rough handling that wipes off the slime"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="2-3 flushes typical. Maintain very high humidity throughout.", duration="7-14 days between flushes", tips=["Consistent near-100% humidity is the key to nameko cultivation", "Excellent in Japanese cuisine — especially miso soup"], common_mistakes=["Humidity fluctuations between flushes", "Expecting nameko to perform in dry environments"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "hardwood sawdust", "logs"],
        contamination_risks=["Bacterial contamination from extreme humidity levels (95-100%)", "Green mold if humidity masks early contamination signs", "Trichoderma during colonization phase", "Bacterial blotch from standing water on substrate surface"],
    ),

    SpeciesProfile(
        id="enoki",
        common_name="Enoki",
        scientific_name="Flammulina velutipes",
        category="gourmet",
        substrate_types=["supplemented hardwood", "hardwood sawdust"],
        colonization_visual_description=(
            "White mycelium, moderate speed. Wild form has brown caps — "
            "commercial white enoki are grown in high-CO2 dark conditions."
        ),
        contamination_risk_notes=(
            "Cold-loving species competes poorly at warm temperatures. "
            "Keep cool to give it advantage over warm-loving contaminants."
        ),
        pinning_trigger_description=(
            "Cold temperatures (35-45°F) trigger pinning. "
            "For long white stems: restrict light + elevate CO2 + use collar."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 21),
                notes="In-bag. Colonization at room temp, then cold-fruit.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=35, temp_max_f=45, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="VERY COLD — near refrigerator temps. This is the coldest-fruiting species.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=38, temp_max_f=50, humidity_min=85, humidity_max=95,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=4, light_hours_off=20, light_spectrum="daylight_6500k",
                light_lux_target=50,
                fae_mode="passive", expected_duration_days=(10, 18),
                notes="For white enoki: low light + high CO2 + collar restricts cap growth → long thin stems. "
                      "Wild form (brown caps): normal light + FAE.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Commercial white style needs collar/tube for stem elongation.",
        tags=["intermediate", "very-cold", "unique-morphology"],
        tldr="Intermediate. Very cold fruiter (38-50°F). Commercial long white enoki = restricted light + high CO2 + cold. Wild type = short with broad caps at normal conditions. 2-3 flushes. Can be shaped with collar/tube for classic long-stem look.",
        flavor_profile="Mild, slightly fruity, with a pleasant crunch. Delicate. Best raw in salads, in soups (add last), or lightly sautéed. The commercial long white variety has the mildest flavor.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust. Pressure sterilize at 15 PSI for 2.5 hours.", duration="4-6 hours", tips=["Beech sawdust is traditional for Japanese enoki production", "20% wheat bran supplementation is standard"], common_mistakes=["Using too much supplementation — increases contamination risk", "Insufficient sterilization"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized substrate bags or bottles with grain spawn at 10% rate.", duration="1-2 hours", tips=["Bottle cultivation (like Japanese commercial production) works well for enoki", "Standard sterile technique required"], common_mistakes=["Non-sterile conditions — enoki competes poorly at warm temperatures", "Uneven spawn distribution"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 65-75°F in darkness for 14-21 days.", duration="14-21 days", tips=["Room temperature colonization is fine, even though fruiting is cold", "Full colonization before the cold phase"], common_mistakes=["Starting cold too early — colonization needs room temperature", "Incomplete colonization"]),
            TekStep(step_number=4, title="Cold Fruiting Initiation", description="Move to VERY cold conditions (35-45°F) — near refrigerator temperature. This is the coldest-fruiting species in the library. Introduce light and moderate FAE.", duration="7-14 days to pins", tips=["A dedicated cold room, wine fridge, or actual refrigerator can work", "This is genuinely refrigerator-cold — the coldest of any cultivated species"], common_mistakes=["Not cold enough — enoki needs genuinely near-freezing temperatures", "Insufficient light — enoki needs some light for normal morphology"]),
            TekStep(step_number=5, title="Morphology Control and Harvest", description="For commercial white enoki style: restrict light (dim, 4 hours), elevate CO2, and use a cardboard or plastic collar around the opening to force long thin stems. For wild-type brown caps: normal light and FAE.", duration="10-18 days", tips=["A collar (rolled cardboard or plastic tube) directs stem elongation for long white enoki", "Wild-type with brown caps has more flavor than commercial white"], common_mistakes=["Expecting long white enoki without a collar — that morphology requires physical restriction", "Too much light for white enoki style — promotes brown cap development"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "hardwood sawdust"],
        contamination_risks=["Cold-loving contaminants (Penicillium) — enoki fruiting temps favor cold-adapted molds", "Bacterial contamination from high humidity in cold conditions", "Trichoderma during warm colonization phase", "Competitor molds take advantage when enoki is moved to cold and grows slowly"],
    ),

    SpeciesProfile(
        id="wood_ear",
        common_name="Wood Ear",
        scientific_name="Auricularia auricula-judae",
        category="gourmet",
        substrate_types=["supplemented hardwood", "hardwood sawdust", "logs"],
        colonization_visual_description=(
            "White mycelium, moderate-fast. Rubbery ear-shaped brown fruiting bodies. "
            "Translucent when thin, opaque when thick."
        ),
        contamination_risk_notes=(
            "Relatively forgiving. Good competitor. Warm-temperature grower. "
            "Standard sterile technique sufficient."
        ),
        pinning_trigger_description=(
            "FAE + light + high humidity. No cold shock needed. "
            "Warm temperatures preferred."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=70, temp_max_f=82, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 21),
                notes="In-bag with filter patch. Likes warmth.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=68, temp_max_f=82, humidity_min=85, humidity_max=95,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(10, 21),
                notes="Harvest when ears reach full size and are still flexible. Dries and rehydrates perfectly.",
            ),
        },
        flush_count_typical=3,
        yield_notes="3-5 flushes. Good yield. Dries extremely well — popular in Asian soups and stir-fry.",
        tags=["beginner", "warm", "forgiving", "dries-well"],
        tldr="Beginner-Intermediate. Warm fruiter (68-80°F). Rubbery ear-shaped bodies. 3-5 flushes. Dries exceptionally well for long-term storage. Popular in Asian cuisine.",
        flavor_profile="Very mild, almost flavorless — valued for its unique crunchy-rubbery texture. Absorbs sauces and seasonings. Essential in hot and sour soup, mu shu, and stir-fries.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust or use hardwood logs. Pressure sterilize sawdust substrates. Logs can be inoculated with plug spawn.", duration="4-6 hours (sawdust) or 2-3 hours (logs)", tips=["Wood ear is forgiving — many hardwoods work", "Log cultivation is reliable and low-maintenance"], common_mistakes=["Using softwood — hardwood is required", "Insufficient hydration of sawdust substrate"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized bags with grain spawn at 10% rate. For logs, drill holes and insert plug spawn.", duration="1-2 hours", tips=["Wood ear is a moderate-strength colonizer", "Standard sterile technique for bags; logs are more forgiving"], common_mistakes=["Poor sterile technique for bag cultivation", "Not sealing log holes with wax"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 70-82°F in darkness for 14-21 days. Wood ear prefers warmth.", duration="14-21 days", tips=["Warmer temperatures speed colonization", "Wood ear grows well in warm climates where cold-weather species struggle"], common_mistakes=["Too cold — wood ear is a warm-weather species", "Insufficient colonization time"]),
            TekStep(step_number=4, title="Fruiting", description="Introduce FAE, 12/12 light, and high humidity. No cold shock needed. Fruiting at 68-82°F. Ear-shaped bodies emerge from substrate.", duration="10-21 days per flush", tips=["High humidity produces thicker, more desirable ear shapes", "Warm and humid — similar to tropical conditions"], common_mistakes=["Insufficient humidity — ears become thin and papery", "Too cold — wood ear prefers warm fruiting"]),
            TekStep(step_number=5, title="Harvest and Drying", description="Harvest when ears reach full size and are still flexible. Wood ear dries exceptionally well and rehydrates perfectly — this is the standard preservation method.", duration="Harvest then dry 6-12 hours", tips=["Dehydrate at 130-140°F until completely dry and brittle", "Rehydrated wood ear is nearly indistinguishable from fresh"], common_mistakes=["Harvesting too late when ears are stiff and tough", "Not drying properly — stored fresh, wood ear spoils quickly"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "hardwood sawdust", "logs"],
        contamination_risks=["Bacterial contamination from warm, humid growing conditions", "Trichoderma during colonization", "Warm conditions favor bacterial and mold growth", "Insect attraction in warm environments"],
    ),

    SpeciesProfile(
        id="shaggy_mane",
        common_name="Shaggy Mane / Ink Cap",
        scientific_name="Coprinus comatus",
        category="gourmet",
        substrate_types=["composted manure", "pasteurized straw", "garden soil mix"],
        colonization_visual_description=(
            "White mycelium, fast. Distinctive tall cylindrical white caps with shaggy scales. "
            "Caps auto-digest (deliquesce) into black ink within hours of maturity."
        ),
        contamination_risk_notes=(
            "Fast colonizer. Compost substrates carry standard risks. "
            "The main challenge is harvesting before auto-digestion, not contamination."
        ),
        pinning_trigger_description=(
            "Casing layer + temperature drop + FAE. Similar to Agaricus. "
            "Casing layer is required for indoor cultivation."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=77, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(10, 18),
                notes="Compost-based substrate. Apply casing layer after colonization.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=55, temp_max_f=65, humidity_min=90, humidity_max=95,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(5, 10),
                notes="Temperature drop after casing colonizes.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=68, humidity_min=85, humidity_max=92,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(5, 10),
                notes="CRITICAL: Harvest IMMEDIATELY when caps elongate, before edges darken. "
                      "Auto-digests into black ink within hours. Cannot be stored — cook immediately.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Must be consumed within hours of harvest. No storage or drying possible.",
        tags=["intermediate", "compost-substrate", "no-storage", "harvest-critical"],
        tldr="Intermediate. Fast fruiting but VERY short shelf life — begins to dissolve (autodigest) into ink within hours of maturity. Must be cooked immediately after harvest. Compost-based substrate.",
        flavor_profile="Delicate, mild, slightly sweet. Excellent flavor but must be eaten within hours of harvest. Dissolves into black ink (autodigestion) rapidly. Cook immediately.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare composted manure or pasteurized straw. Shaggy mane is a compost-loving species similar to button mushrooms. A casing layer is required.", duration="4-12 hours", tips=["Composted horse manure is the preferred substrate", "Garden soil/compost mix works for outdoor beds"], common_mistakes=["Using non-composted substrate — shaggy mane needs partially decomposed organic matter", "Forgetting the casing layer — essential for pinning"]),
            TekStep(step_number=2, title="Spawning and Casing", description="Mix grain spawn with pasteurized compost at 10% rate. After full colonization, apply a casing layer of peat moss and vermiculite (50/50).", duration="1 hour + colonization time", tips=["Casing layer should be 1/2 inch thick", "Pasteurize casing layer in the microwave"], common_mistakes=["Skipping casing — will not fruit without it", "Casing too thick or too thin"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 68-77°F for 10-18 days. Wait for casing layer to show mycelial threads.", duration="10-18 days", tips=["Moderate colonizer — standard patience required", "Casing colonization is the signal for fruiting readiness"], common_mistakes=["Fruiting before casing is colonized", "Temperature fluctuations"]),
            TekStep(step_number=4, title="Fruiting", description="Cool to 55-68°F, introduce FAE, 12/12 light. Tall cylindrical white mushrooms with shaggy scales emerge.", duration="5-10 days per flush", tips=["The tall cylindrical shape is distinctive and unmistakable", "Prepare for EXTREMELY short harvest window"], common_mistakes=["Not monitoring daily — harvest window is measured in hours", "Insufficient FAE during fruiting"]),
            TekStep(step_number=5, title="IMMEDIATE Harvest", description="CRITICAL: Shaggy mane auto-digests (deliquesces) into black ink within hours of maturity. Harvest IMMEDIATELY when caps elongate, BEFORE edges darken. Cook immediately — zero storage time.", duration="Harvest and cook same hour", tips=["Check twice daily minimum — the window from ready to ink is just a few hours", "Have a pan ready — you need to cook these within an hour of harvest"], common_mistakes=["CRITICAL: Missing the harvest window — caps dissolve into black ink and are lost", "Trying to store for later — there is no 'later' with shaggy mane"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Composted Manure", ingredients={"composted horse manure": "5 quarts", "straw": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="optimal", notes="Composted manure is the natural substrate. Add peat/verm casing layer."),
        ],
        substrate_preference_ranking=["composted manure", "pasteurized straw", "garden soil mix"],
        contamination_risks=["Bacterial contamination from manure-based substrate", "Auto-digestion (deliquescence) if harvest timing is missed — not contamination but total crop loss", "Competitor molds on improperly composted substrate", "Short fruiting window makes daily monitoring essential"],
    ),

    SpeciesProfile(
        id="elm_oyster",
        common_name="Elm Oyster",
        scientific_name="Hypsizygus ulmarius",
        category="gourmet",
        substrate_types=["supplemented hardwood", "masters mix", "elm/beech sawdust"],
        colonization_visual_description=(
            "White mycelium, moderate speed. Large white to cream caps — "
            "bigger individual fruits than standard oysters."
        ),
        contamination_risk_notes=(
            "Moderate-slow colonizer. Standard contamination risks. "
            "Less aggressive than Pleurotus oysters."
        ),
        pinning_trigger_description=(
            "Cold shock + FAE + light. Similar to beech/shimeji. "
            "Fruits from top of block."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 28),
                notes="Slower than Pleurotus oysters. Full colonization required.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=50, temp_max_f=60, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(7, 14),
                notes="Cold shock beneficial. Remove from bag for top-fruiting.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=68, humidity_min=85, humidity_max=92,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(10, 18),
                notes="Large individual caps. Meaty texture. Harvest before edges flatten.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Large meaty caps. Good texture for cooking.",
        tags=["intermediate", "slow", "large-fruits"],
        tldr="Beginner-Intermediate. Large-fruited oyster variant. Standard oyster cultivation. Slightly slower than standard oysters.",
        flavor_profile="Mild, similar to pearl oyster but with a slightly more robust, earthy character. Good all-purpose mushroom.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Chop straw into 2-4 inch pieces (or use hardwood pellets). Pasteurize using hot water bath at 160-170°F for 60-90 minutes, or use cold water lime bath for 18-24 hours. Drain and cool to room temperature.", duration="4-24 hours depending on method", tips=["Hot water pasteurization is faster; cold lime bath is simpler and uses no fuel", "Straw should be damp like a wrung-out sponge, not dripping"], common_mistakes=["Under-pasteurizing — remaining contaminants will outcompete the mycelium", "Not draining thoroughly — excess water pools at the bottom and breeds bacteria"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Layer or mix grain spawn with cooled pasteurized straw inside grow bags (with filter patch) or 5-gallon buckets (with holes drilled). Target 10% spawn rate. Pack firmly but not overly tight.", duration="30-60 minutes", tips=["5-gallon buckets with 1/2-inch holes every 6 inches are cheap and effective", "Pack substrate firmly to eliminate air pockets"], common_mistakes=["Too little spawn — slow colonization invites contamination", "Not packing firmly enough — air gaps create dry spots that do not colonize"]),
            TekStep(step_number=3, title="Colonization", description="Store bags or buckets in a dark location at the species-appropriate temperature. Colonization takes 10-14 days for most oyster species. White mycelium should fully cover all substrate.", duration="10-14 days", tips=["Slight warmth speeds colonization — oysters are aggressive colonizers", "Small amounts of condensation inside bags is normal"], common_mistakes=["Storing in a location with wide temperature swings", "Not waiting for full colonization — patches of uncolonized straw are contamination entry points"]),
            TekStep(step_number=4, title="Fruiting Initiation", description="Cut X-shaped slits or holes in bags (or buckets already have holes). Move to a well-ventilated space with indirect light. Introduce temperature drop if required by species. Mist 2-3x daily.", duration="3-7 days to first pins", tips=["Pins form at the holes/slits where fresh air meets the colonized substrate", "A simple fan on a timer provides consistent FAE"], common_mistakes=["Insufficient ventilation — oysters are very CO2-sensitive", "Placing in direct sunlight — indirect light is sufficient"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Mushroom clusters grow rapidly from the openings. Harvest when cap edges begin to flatten or just before they upturn. Twist and pull the entire cluster or cut at the base.", duration="5-7 days per flush", tips=["Harvest the entire cluster at once rather than individual mushrooms", "Harvest before caps fully flatten to maximize shelf life and reduce spore load"], common_mistakes=["Waiting too long — caps upturn, spore load increases, flesh becomes tough", "Pulling too hard and tearing substrate from the holes"]),
            TekStep(step_number=6, title="Subsequent Flushes", description="After harvest, continue misting and maintaining FAE. Next flush typically appears in 7-14 days. Most oyster species produce 3-4 flushes from straw substrates.", duration="7-14 days between flushes", tips=["Soak the block/bucket for a few hours between flushes if it feels light and dry", "Yield decreases with each subsequent flush — first flush is always the largest"], common_mistakes=["Stopping care after first flush — oysters are reliable multi-flushers", "Over-soaking between flushes — 2-4 hour soak is sufficient, not 24 hours"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "masters mix", "elm/beech sawdust"],
        contamination_risks=["Trichoderma during slower colonization (14-28 days)", "Bacterial contamination at high humidity", "Slower than Pleurotus oysters — more vulnerable to contamination", "Green mold on insufficient sterilized supplemented substrate"],
    ),

    SpeciesProfile(
        id="blewit",
        common_name="Wood Blewit",
        scientific_name="Lepista nuda",
        category="gourmet",
        substrate_types=["composted leaf litter", "composted straw", "garden compost"],
        colonization_visual_description=(
            "Lilac-purple mycelium — the purple color is normal and distinctive. "
            "Beautiful violet-blue caps and stems. Saprobic on decomposed organic matter."
        ),
        contamination_risk_notes=(
            "Compost-based substrate. Slower colonizer than oysters. "
            "The distinctive purple mycelium makes contamination easier to spot."
        ),
        pinning_trigger_description=(
            "Cool temperatures + moisture + casing layer. "
            "Naturally fruits in autumn. Cold shock beneficial."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=60, temp_max_f=72, humidity_min=80, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(21, 42),
                notes="Composted substrate. Purple/lilac mycelium is normal. Slow colonizer.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=45, temp_max_f=55, humidity_min=90, humidity_max=95,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Cold shock triggers pinning. Casing layer helpful.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=50, temp_max_f=64, humidity_min=85, humidity_max=92,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(10, 21),
                notes="Beautiful violet-blue caps. Must be cooked — mild toxin destroyed by heat. "
                      "Harvest when caps flatten.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Moderate yield. Beautiful purple color. Must be cooked before eating.",
        tags=["intermediate", "cold-tolerant", "compost-substrate", "colorful", "cook-required"],
        tldr="Intermediate. Cold-tolerant species with distinctive purple mycelium. Compost/leaf litter substrate. Outdoor beds or cold indoor fruiting. MUST be cooked — mildly toxic raw.",
        flavor_profile="Floral, perfume-like aroma. Lilac/purple color. Mild sweetness. MUST be thoroughly cooked (mildly toxic raw). Unique among culinary mushrooms for its fragrance.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare composted leaf litter or well-composted straw. Blewit is a saprophyte of decomposed organic matter. Can also be grown in outdoor garden beds with composted material.", duration="Composting: weeks | Prep: 4-12 hours", tips=["Well-aged leaf litter compost is the natural substrate", "Outdoor garden beds are often more successful than indoor cultivation"], common_mistakes=["Using fresh, uncomposted material — blewit needs partially decomposed organic matter", "Using manure instead of leaf litter — blewit prefers leaf/plant compost"]),
            TekStep(step_number=2, title="Spawning", description="Mix grain spawn with composted substrate at 10% rate. For outdoor beds, layer spawn between layers of composted leaves/straw.", duration="1-2 hours", tips=["Outdoor bed cultivation is often more reliable for blewit", "Purple mycelium is normal and distinctive for this species"], common_mistakes=["Expecting white mycelium — blewit mycelium is lilac/purple", "Using too little spawn for outdoor beds"]),
            TekStep(step_number=3, title="Extended Colonization", description="Incubate at 60-72°F for 21-42 days. Blewit is a slow colonizer. Purple mycelium will spread through the compost.", duration="21-42 days", tips=["The purple mycelium makes contamination very easy to identify", "Patience is essential — this is a slow species"], common_mistakes=["Mistaking the purple mycelium for contamination", "Rushing colonization"]),
            TekStep(step_number=4, title="Cold-Triggered Fruiting", description="Cool to 45-55°F. Add casing layer if growing indoors. Blewit naturally fruits in autumn. Beautiful violet-blue caps.", duration="7-14 days to pins", tips=["Cold shock is important for indoor cultivation", "Casing layer improves pinning success indoors"], common_mistakes=["Insufficient cold shock", "No casing layer for indoor grows"]),
            TekStep(step_number=5, title="Harvest", description="Harvest when caps flatten. IMPORTANT: Wood blewit MUST be thoroughly cooked — mildly toxic when raw. Beautiful purple-blue color.", duration="10-21 days per flush", tips=["MUST be cooked — mild toxin destroyed by heat", "Beautiful purple color makes a stunning culinary presentation"], common_mistakes=["CRITICAL: Eating raw or undercooked blewit — causes gastrointestinal distress", "Waiting too long — older specimens lose color and flavor"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Composted Leaf Litter", ingredients={"composted deciduous leaves": "5 quarts", "composted straw": "2 quarts", "gypsum": "1/2 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Well-aged leaf litter compost is the natural substrate for blewit."),
        ],
        substrate_preference_ranking=["composted leaf litter", "composted straw", "garden compost"],
        contamination_risks=["Competitor molds on compost substrate — outdoor beds have more exposure", "Slow colonization (21-42 days) creates a long contamination window", "Bacterial contamination in wet, cool conditions", "MUST be cooked — raw blewit causes gastrointestinal issues (not a contamination issue but a safety concern)"],
    ),

    SpeciesProfile(
        id="snow_fungus",
        common_name="Snow Fungus / White Jelly",
        scientific_name="Tremella fuciformis",
        category="gourmet",
        substrate_types=["supplemented hardwood sawdust"],
        colonization_visual_description=(
            "Unique: Tremella is a mycoparasite — it requires a host fungus (typically Annulohypoxylon "
            "or Hypoxylon) growing on the same substrate. White, translucent, jelly-like ruffled fronds."
        ),
        contamination_risk_notes=(
            "Requires co-culture with host fungus. More complex than single-species cultivation. "
            "Commercial spawn comes pre-inoculated with both organisms."
        ),
        pinning_trigger_description=(
            "High humidity + warmth + light. Fruits when host fungus is established. "
            "Tropical species — likes warm, humid conditions."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=72, temp_max_f=82, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(21, 35),
                notes="Co-culture: Tremella + host fungus (Annulohypoxylon). "
                      "Commercial spawn includes both. Warm temperatures preferred.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=73, temp_max_f=82, humidity_min=90, humidity_max=98,
                co2_max_ppm=1500, co2_tolerance="high",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="passive", expected_duration_days=(10, 21),
                notes="VERY high humidity required. Translucent white jelly fronds. "
                      "Harvest when fronds are full-sized but still firm.",
            ),
        },
        flush_count_typical=2,
        yield_notes="1-3 flushes. Gelatinous texture prized in Asian desserts and soups. "
                    "Dries well and rehydrates perfectly.",
        tags=["intermediate", "tropical", "co-culture", "high-humidity", "dessert"],
        tldr="Advanced. Unique mycoparasite — requires co-culture with a helper fungus (Annulohypoxylon stygium). Tropical temperatures. Produces translucent white jelly-like fruiting bodies.",
        flavor_profile="Nearly flavorless — valued for texture. Soft, gelatinous, slightly crunchy. Used in Chinese dessert soups, sweet drinks, and skincare. Prized for collagen-like properties.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust. Pressure sterilize at 15 PSI for 2.5 hours. Snow fungus is a mycoparasite — it requires a co-culture with a helper fungus.", duration="4-6 hours", tips=["Commercial snow fungus spawn comes pre-inoculated with both organisms (Tremella + host)", "Do not try to isolate snow fungus alone — it needs the host"], common_mistakes=["Trying to grow Tremella without its host fungus — it will not fruit", "Not understanding the co-culture requirement"]),
            TekStep(step_number=2, title="Inoculation (Co-Culture)", description="Inoculate with commercial co-culture spawn containing both Tremella fuciformis and its host (Annulohypoxylon). Standard sterile technique.", duration="1-2 hours", tips=["Source spawn from reputable suppliers who understand the co-culture", "The host fungus colonizes first, then Tremella parasitizes it"], common_mistakes=["Using Tremella-only spawn — will colonize but not fruit", "Impatience — the co-culture relationship takes time to establish"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 72-82°F in darkness for 21-35 days. The host fungus colonizes first, followed by Tremella.", duration="21-35 days", tips=["Warm tropical conditions speed colonization", "The dual organism relationship means colonization is slower than single-species cultivation"], common_mistakes=["Too cold — tropical species needs warmth", "Disturbing the delicate co-culture relationship"]),
            TekStep(step_number=4, title="Fruiting", description="Maintain 73-82°F with VERY high humidity (90-98%). Light 12/12. Snow fungus produces translucent white jelly-like ruffled fronds.", duration="10-21 days", tips=["Near-100% humidity is essential for the gelatinous texture", "Fruits should be translucent white and gelatinous"], common_mistakes=["Insufficient humidity — fronds become dry and papery", "Too cold — tropical species"]),
            TekStep(step_number=5, title="Harvest and Drying", description="Harvest when fronds are full-sized but still firm. Snow fungus dries well and rehydrates perfectly. Widely used dried in Asian cooking.", duration="Dry at 130°F for 6-12 hours", tips=["Dried snow fungus rehydrates to near-fresh quality", "Popular in Chinese dessert soups and sweet drinks"], common_mistakes=["Harvesting too late when fronds become soggy", "Not drying properly for storage"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
        ],
        substrate_preference_ranking=["supplemented hardwood sawdust"],
        contamination_risks=["Co-culture complexity — failure of host fungus means no Tremella fruiting", "Bacterial contamination from extreme humidity levels", "Warm tropical conditions favor bacterial growth", "Competitor molds can outcompete the slower Tremella"],
    ),

    SpeciesProfile(
        id="paddy_straw",
        common_name="Paddy Straw / Straw Mushroom",
        scientific_name="Volvariella volvacea",
        category="gourmet",
        substrate_types=["rice straw", "cotton waste", "oil palm waste"],
        colonization_visual_description=(
            "Fast white mycelium. Fruits emerge from a volva (egg-like sac). "
            "Very popular in Southeast Asian cuisine — the canned 'straw mushroom'."
        ),
        contamination_risk_notes=(
            "Tropical species requiring high temperatures. Fast colonizer at warm temps. "
            "Bacterial contamination is the main risk in hot, humid conditions."
        ),
        pinning_trigger_description=(
            "High temperature + high humidity. No cold shock — tropical species. "
            "Fruits rapidly once conditions are right."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=86, temp_max_f=95, humidity_min=85, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(4, 7),
                notes="VERY WARM — 86-95°F required. Tropical species. "
                      "Fastest colonizer in this library.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=82, temp_max_f=93, humidity_min=85, humidity_max=95,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(4, 7),
                notes="Harvest in egg/button stage — before volva opens. "
                      "Very fast cycle — can fruit within 10 days of inoculation.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Extremely fast cycle. Harvest at egg stage. Cannot be refrigerated long.",
        tags=["intermediate", "tropical", "very-warm", "fast-cycle"],
        tldr="Intermediate. Tropical rapid-cycle species (75-95°F). Very fast but temperature sensitive. Used heavily in Southeast Asian cuisine. Short shelf life.",
        flavor_profile="Mild, slightly sweet, with a smooth silky texture. Best known as the mushroom in Thai tom yum soup and Chinese stir-fries. Always sold canned outside Asia due to short shelf life.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Soak rice straw or cotton waste in water for 24 hours, then pasteurize at 160-170°F for 90 minutes. Paddy straw requires VERY WARM conditions (86-95°F).", duration="24-hour soak + 4 hours", tips=["Rice straw is the traditional substrate — the species is named for it", "This is the warmest-growing species in the library"], common_mistakes=["Using temperatures too cool — paddy straw needs genuine tropical heat", "Not pasteurizing thoroughly — fast cycle at warm temps means quick contamination if substrate is not clean"]),
            TekStep(step_number=2, title="Spawning", description="Mix grain spawn with pasteurized rice straw at 10% rate. Layer in trays or beds. The extremely warm conditions speed colonization dramatically.", duration="1 hour", tips=["Layer spawn between layers of straw for even colonization", "Keep very warm — 86-95°F is the colonization range"], common_mistakes=["Growing at standard mushroom temperatures — far too cold for paddy straw", "Insufficient spawn — fast cycle needs good coverage"]),
            TekStep(step_number=3, title="Rapid Colonization", description="Colonizes in just 4-7 days at 86-95°F — the fastest colonizer in the library.", duration="4-7 days", tips=["This is the fastest species — can go from spawn to fruit in 10 days total", "Maintain very warm, humid conditions throughout"], common_mistakes=["Temperature drops below 82°F stall colonization", "Not having fruiting space ready — the speed catches people off guard"]),
            TekStep(step_number=4, title="Fruiting and Harvest", description="Fruits emerge from a volva (egg-like sac). Harvest at egg/button stage — before the volva opens. Extremely fast fruiting cycle.", duration="4-7 days per flush", tips=["Harvest in the egg stage for the best culinary result", "The volva (egg sac) is the identifying feature"], common_mistakes=["Letting caps open — flavor and texture decline rapidly", "Not checking daily — the cycle is very fast"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Rice Straw", ingredients={"rice straw": "5 lbs", "water": "as needed"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="The traditional substrate — species is named for it. Requires 86-95°F."),
        ],
        substrate_preference_ranking=["rice straw", "cotton waste", "oil palm waste"],
        contamination_risks=["Bacterial contamination from extremely warm, humid conditions", "Fast growing molds that also thrive at 86-95°F", "Very short shelf life post-harvest — process immediately", "Non-sterile substrate at high temperatures creates ideal conditions for competitors"],
    ),

    SpeciesProfile(
        id="cauliflower_mushroom",
        common_name="Cauliflower Mushroom",
        scientific_name="Sparassis crispa",
        category="gourmet",
        substrate_types=["conifer wood", "pine/fir sawdust", "supplemented softwood"],
        colonization_visual_description=(
            "White mycelium, slow. Unique ruffled/lobed structure resembling cauliflower or sea sponge. "
            "Large single fruit body can reach several pounds."
        ),
        contamination_risk_notes=(
            "Very slow colonizer — high contamination risk from extended timeline. "
            "Prefers conifer (softwood) substrate, unusual among culinary species."
        ),
        pinning_trigger_description=(
            "Cool temperatures + FAE + light after extended colonization. "
            "Single large fruit body forms gradually."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(30, 60),
                notes="Very slow. Prefers conifer (softwood) substrates — unusual for edibles. "
                      "Full colonization before fruiting.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=68, humidity_min=85, humidity_max=95,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(21, 42),
                notes="Single large ruffled fruit body. Harvest when lobes are firm and white. "
                      "Excellent culinary mushroom — nutty, pasta-like texture.",
            ),
        },
        flush_count_typical=1,
        yield_notes="1-2 fruitings. Single large fruit body. Premium culinary mushroom.",
        tags=["advanced", "slow", "softwood", "premium-gourmet", "large-fruits"],
        tldr="Advanced. Softwood specialist (pine, spruce). Slow colonizer. Large ruffled cauliflower-like clusters. Premium gourmet. 1-2 flushes.",
        flavor_profile="Mild, nutty, with a unique pasta-like noodle texture. Tear into pieces and sauté. Absorbs sauces beautifully. Among the most expensive gourmet mushrooms.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare conifer (softwood) sawdust — pine, spruce, or fir. This is unique among edible species — most require hardwood. Pressure sterilize at 15 PSI for 2.5 hours.", duration="4-6 hours", tips=["Conifer sawdust is the only appropriate substrate — hardwood works poorly", "No supplementation needed — pure conifer sawdust is sufficient"], common_mistakes=["Using hardwood — cauliflower mushroom is a softwood specialist", "Adding supplements that increase contamination risk during the very long colonization"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized conifer sawdust bags with grain spawn at 10% rate. Flow hood essential due to extremely long colonization cycle ahead.", duration="1-2 hours", tips=["Absolutely sterile technique — 30-60 day colonization ahead", "Use vigorous, fresh spawn"], common_mistakes=["Any sterility break — 30-60 day colonization will amplify it", "Old or weak spawn"]),
            TekStep(step_number=3, title="Extended Colonization", description="Incubate at 65-75°F for 30-60 days. Very slow colonizer. Full colonization is critical.", duration="30-60 days", tips=["Set a calendar reminder — this takes as long as shiitake", "White mycelium on conifer substrate is the expected appearance"], common_mistakes=["Premature fruiting", "Fluctuating temperatures"]),
            TekStep(step_number=4, title="Fruiting", description="Move to 55-68°F with FAE and light. A single large ruffled fruit body forms gradually. This is a slow-growing fruit that builds over 3-6 weeks.", duration="21-42 days", tips=["The fruit body builds slowly — do not expect fast results", "Single large specimen can reach several pounds"], common_mistakes=["Expecting fast fruiting — cauliflower mushroom is slow at every stage", "Insufficient humidity during the long fruiting period"]),
            TekStep(step_number=5, title="Harvest", description="Harvest when lobes are firm and white. A single fruit body can weigh several pounds. Premium gourmet mushroom with pasta-like noodle texture.", duration="Single harvest", tips=["Tear into pieces and sauté — the texture resembles egg noodles", "Among the most expensive gourmet mushrooms at market"], common_mistakes=["Waiting until lobes yellow — flavor declines", "Rough handling of the delicate ruffled structure"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Conifer Sawdust", ingredients={"pine/fir/spruce sawdust": "5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Pure conifer (softwood) sawdust — unique among gourmet species. No supplementation needed."),
        ],
        substrate_preference_ranking=["conifer wood", "pine/fir sawdust", "supplemented softwood"],
        contamination_risks=["Trichoderma during 30-60 day colonization — very high exposure window", "Competitor molds on softwood substrate", "Bacterial contamination during extended fruiting period", "Very slow at every stage — contaminants have maximum opportunity"],
    ),

    SpeciesProfile(
        id="chicken_of_the_woods",
        common_name="Chicken of the Woods",
        scientific_name="Laetiporus sulphureus",
        category="gourmet",
        substrate_types=["hardwood logs (oak)", "hardwood sawdust blocks", "buried wood"],
        colonization_visual_description=(
            "White mycelium, slow on sawdust. Bright orange and yellow shelf brackets. "
            "Brown rot fungus — digests cellulose, leaves lignin."
        ),
        contamination_risk_notes=(
            "Slow colonizer on sawdust — high contamination risk. "
            "Log cultivation is more reliable. Good competitor once established."
        ),
        pinning_trigger_description=(
            "Warmth + moisture after extended colonization. "
            "Log-based cultivation outdoors is most reliable."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=70, temp_max_f=80, humidity_min=80, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(60, 180),
                notes="Very slow on sawdust. Log inoculation is traditional. "
                      "Can take 6+ months to colonize.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=65, temp_max_f=80, humidity_min=80, humidity_max=95,
                co2_max_ppm=1500, co2_tolerance="high",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="passive", expected_duration_days=(14, 28),
                notes="Bright orange/yellow shelves. Harvest young — tender and chicken-like. "
                      "Older growth becomes tough. NOTE: Some people are sensitive — try small amount first.",
            ),
        },
        flush_count_typical=1,
        yield_notes="1-2 fruitings per season on logs. Indoor sawdust cultivation is experimental. "
                    "Taste and texture remarkably similar to chicken.",
        tags=["advanced", "slow", "log-cultivation", "outdoor-capable", "chicken-texture"],
        tldr="Advanced. Very slow colonizer (6-18 months on logs). Outdoor long-term project. Unreliable indoors. Dramatic orange/yellow shelves. Seasonal fruiting. Avoid specimens from eucalyptus/cedar/conifers.",
        flavor_profile="Remarkably chicken-like flavor and texture — the most convincing meat substitute in the fungal kingdom. Best young when edges are tender. Older growth gets tough. Excellent breaded and fried, in tacos, or as chicken substitute in any recipe.",
        tek_guide=[
            TekStep(step_number=1, title="Log Selection and Preparation", description="Select freshly cut hardwood logs (oak preferred), 6-12 inches diameter. Cut 2-4 weeks before inoculation. Indoor sawdust cultivation is experimental and unreliable.", duration="Log procurement: days", tips=["Oak is the preferred host wood — avoid conifers, eucalyptus, and cedar", "Fresh-cut logs work best — not seasoned wood"], common_mistakes=["Using conifer or eucalyptus logs — can produce toxic compounds", "Using old, dried-out logs"]),
            TekStep(step_number=2, title="Log Inoculation", description="Drill holes every 4-6 inches in a diamond pattern. Insert plug spawn. Seal holes with cheese wax. This is a long-term outdoor project.", duration="2-3 hours per log", tips=["Spring inoculation gives the best results", "Diamond pattern ensures even colonization"], common_mistakes=["Not sealing holes with wax — contamination entry point", "Insufficient plug count — use 30-50 per log"]),
            TekStep(step_number=3, title="Extended Colonization", description="Stack inoculated logs in a shaded outdoor location. Keep moist. Colonization takes 6-18 MONTHS. This is a very long-term project.", duration="6-18 months", tips=["A shaded north-facing spot is ideal", "Water logs during dry spells"], common_mistakes=["Expecting results in weeks — this takes 6-18 months minimum", "Letting logs dry out completely"]),
            TekStep(step_number=4, title="Fruiting (Seasonal)", description="Bright orange and yellow shelf brackets emerge from the log, typically in late spring through early autumn. Fruiting is seasonal and natural.", duration="Seasonal occurrence", tips=["Fruiting may not occur until the second year", "Multiple years of production from a single log"], common_mistakes=["Giving up before the first fruiting — it takes time", "Not checking logs regularly during fruiting season"]),
            TekStep(step_number=5, title="Harvest", description="Harvest young tender growth when edges are still bright orange and pliable. Older growth becomes tough. NOTE: Some people have sensitivity — try a small amount first.", duration="Harvest as they appear", tips=["Young tender edges are the best eating", "Always cook thoroughly — never eat raw"], common_mistakes=["Harvesting when growth is old and tough — woody texture", "Not doing a test taste for sensitivity — some people react to this species"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Hardwood Log Cultivation", ingredients={"fresh oak log": "6-12 inch diameter x 3-4 feet", "plug spawn": "30-50 plugs per log", "cheese wax": "as needed"}, water_liters_per_liter_substrate=0.0, spawn_rate_percent=5, sterilization_method="pasteurize_hot_water", sterilization_time_min=0, sterilization_temp_f=None, suitability="optimal", notes="Log cultivation is the only reliable method. Indoor sawdust is experimental."),
        ],
        substrate_preference_ranking=["hardwood logs (oak)", "hardwood sawdust blocks", "buried wood"],
        contamination_risks=["Competitor fungi colonizing the same logs — common in outdoor cultivation", "Insect and slug damage to emerging fruit bodies", "Very slow colonization gives maximum exposure to outdoor contaminants", "CRITICAL: Never harvest from eucalyptus, cedar, or conifer hosts — can concentrate toxic compounds"],
    ),

    # ─── MEDICINAL SPECIES ──────────────────────────────────────────────
    SpeciesProfile(
        id="white_beech",
        common_name="White Beech / Bunashimeji",
        scientific_name="Hypsizygus tessellatus",
        category="gourmet",
        substrate_types=["supplemented hardwood", "masters mix"],
        colonization_visual_description=(
            "White mycelium, slow-moderate. Forms dense clusters of small white or brown-capped "
            "mushrooms with thin stems. Commercial bunashimeji."
        ),
        contamination_risk_notes=(
            "Slow colonizer — higher contamination risk. "
            "Supplemented substrate needs proper sterilization."
        ),
        pinning_trigger_description=(
            "Cold shock (45-55°F) + FAE + light. "
            "Fruits from top of block in dense clusters."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(21, 35),
                notes="Slow colonizer. Full colonization required before fruiting.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=45, temp_max_f=55, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(7, 14),
                notes="Needs significant cold shock. Remove from bag and top-fruit.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=50, temp_max_f=64, humidity_min=85, humidity_max=92,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(10, 18),
                notes="Harvest clusters when caps are still convex. Bitter if overripe.",
            ),
        },
        flush_count_typical=2,
        yield_notes="2-3 flushes. Dense clusters. Popular in Japanese/Korean cuisine. Must be cooked — bitter raw.",
        tags=["intermediate", "slow", "cold-tolerant", "japanese"],
        tldr="Intermediate. Cold fruiter (50-60°F). Grows in tight clusters. 21-30 day colonization. BITTER raw — must be cooked. 2-3 flushes.",
        flavor_profile="Nutty, savory, with a mild sweetness when cooked. Firm crunchy texture. BITTER when raw. Excellent in stir-fries, ramen, and risotto. Cook thoroughly.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust or Masters Mix. Pressure sterilize at 15 PSI for 2.5 hours.", duration="4-6 hours", tips=["Beech sawdust is traditional and preferred", "Masters Mix works well for this species"], common_mistakes=["Using straw — white beech requires supplemented hardwood", "Insufficient sterilization"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized substrate bags with grain spawn at 10% rate using flow hood.", duration="1-2 hours", tips=["Flow hood required — white beech is a slow colonizer that needs sterile conditions", "Even spawn distribution helps with the slow colonization"], common_mistakes=["Poor sterile technique", "Uneven spawn placement"]),
            TekStep(step_number=3, title="Extended Colonization", description="Incubate at 65-75°F in darkness for 21-35 days. White beech is a slow colonizer.", duration="21-35 days", tips=["Full colonization is essential — do not rush", "Moderate-slow colonizer requires patience"], common_mistakes=["Premature fruiting", "Temperature fluctuations"]),
            TekStep(step_number=4, title="Cold Shock Fruiting", description="Cold shock to 45-55°F. Remove block from bag, exposing top surface. Introduce FAE and 12/12 light. Dense clusters form from the top.", duration="7-14 days to pins", tips=["Significant cold shock needed — 45-55°F, not just slightly cool", "Top-fruiting in dense clusters is characteristic"], common_mistakes=["Insufficient cold shock temperature", "Not removing from bag for top-fruiting"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain 50-64°F with moderate FAE. Harvest clusters when caps are still convex. White beech is BITTER when raw — must be cooked.", duration="10-18 days per flush", tips=["MUST be cooked — bitter and unpleasant when raw", "Harvest while caps are still convex for best texture"], common_mistakes=["Eating raw — very bitter taste", "Waiting until caps flatten — texture and flavor decline"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "masters mix"],
        contamination_risks=["Trichoderma during slow 21-35 day colonization", "Green mold from insufficiently sterilized substrate", "Bacterial contamination at high humidity during fruiting", "Slow colonization gives contaminants more time to establish"],
    ),

    SpeciesProfile(
        id="button_mushroom",
        common_name="Button / Cremini / Portobello",
        scientific_name="Agaricus bisporus",
        category="gourmet",
        substrate_types=["composted manure", "commercial mushroom compost"],
        colonization_visual_description=(
            "White mycelium through compost substrate. Requires casing layer (peat + vermiculite) "
            "to trigger pinning. The world's most consumed mushroom."
        ),
        contamination_risk_notes=(
            "Compost substrate must be properly prepared (Phase I + Phase II composting). "
            "Green mold, cobweb, and competitor molds are common on bad compost. "
            "Casing layer contamination possible."
        ),
        pinning_trigger_description=(
            "Casing layer application after full colonization + temperature drop + FAE. "
            "Casing layer is REQUIRED — will not pin without it."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=72, temp_max_f=78, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(14, 21),
                notes="Compost-based substrate. Apply casing layer after full colonization.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=60, temp_max_f=65, humidity_min=90, humidity_max=95,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Temperature drop after casing colonizes. No light needed. "
                      "Button mushrooms don't need light at any stage.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=58, temp_max_f=65, humidity_min=85, humidity_max=92,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Button: harvest when caps are closed. Cremini: slightly larger. "
                      "Portobello: let caps open fully. Same species, different harvest times.",
            ),
            GrowPhase.REST: PhaseParams(
                temp_min_f=60, temp_max_f=65, humidity_min=85, humidity_max=95,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(7, 10),
                notes="Water casing layer between flushes. Keep moist but not soaked.",
            ),
        },
        flush_count_typical=3,
        yield_notes="3-4 flushes. World's most consumed mushroom. Requires composted substrate + casing layer.",
        tags=["intermediate", "compost-substrate", "casing-required", "no-light"],
        tldr="Beginner-Intermediate. World's most consumed mushroom. All the same species at different stages. Composted manure substrate. Requires casing layer. 3-4 flushes.",
        flavor_profile="Button: mild, clean. Cremini: earthier, deeper. Portobello: rich, meaty, substantial. The universal cooking mushroom. Portobellos make excellent burger substitutes when grilled.",
        tek_guide=[
            TekStep(step_number=1, title="Compost Preparation", description="Prepare composted manure substrate. Commercial mushroom compost requires Phase I (outdoor composting, 2-3 weeks) and Phase II (pasteurization at 140°F, 4-6 hours). This is the most complex substrate preparation in the library.", duration="2-4 weeks for composting + 6 hours pasteurization", tips=["Pre-made commercial mushroom compost is strongly recommended for home growers", "Horse manure + straw bedding is the traditional base"], common_mistakes=["Trying to skip the composting process — button mushrooms NEED properly composted substrate", "Using fresh manure — must be composted through Phase I and Phase II"]),
            TekStep(step_number=2, title="Spawning and Casing", description="Mix grain spawn into cooled compost at 5-10% rate. Fill trays 6-8 inches deep. After colonization, apply casing layer (peat moss + vermiculite 50/50, 1 inch thick). Casing layer is REQUIRED.", duration="1-2 hours + 14-21 days colonization", tips=["Casing layer is absolutely essential — no casing = no pinning", "Peat + vermiculite at 50/50 is the standard casing mix"], common_mistakes=["CRITICAL: Skipping the casing layer — buttons will NOT pin without it", "Using non-pasteurized casing material"]),
            TekStep(step_number=3, title="Colonization Through Casing", description="After casing application, maintain 72-78°F. Wait for mycelial threads to penetrate the casing layer (7-14 days). No light needed at any stage for button mushrooms.", duration="7-14 days after casing", tips=["Button mushrooms are one of the few species that need NO light", "Wait for visible mycelial threads in the casing before temperature drop"], common_mistakes=["Adding light — unnecessary and wastes energy", "Dropping temperature before casing is threaded"]),
            TekStep(step_number=4, title="Fruiting", description="Drop temperature to 58-65°F, introduce FAE. No light needed. Mushrooms emerge through the casing layer. Button = small closed caps. Cremini = medium. Portobello = fully open.", duration="7-14 days per flush", tips=["All three market names (button, cremini, portobello) are the SAME species at different harvest stages", "Control your product by choosing when to harvest"], common_mistakes=["Adding light — Agaricus bisporus does not need it", "Not understanding that button/cremini/portobello are harvest timing, not varieties"]),
            TekStep(step_number=5, title="Harvest", description="Button stage: harvest when caps are closed and round. Cremini: slightly larger with brown color. Portobello: let caps open fully. Water casing layer between flushes.", duration="3-4 flushes", tips=["3-4 flushes is typical from a well-prepared compost tray", "Keep casing moist between flushes — mist lightly"], common_mistakes=["Letting casing dry out between flushes — dramatically reduces yield", "Over-watering casing — pooling water breeds bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Commercial Mushroom Compost", ingredients={"composted horse manure + straw": "as needed", "gypsum": "5% by weight", "peat moss casing": "1 inch", "vermiculite casing": "1 inch"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=5, sterilization_method="pasteurize_hot_water", sterilization_time_min=360, sterilization_temp_f=140, suitability="optimal", notes="Phase I + Phase II composting required. Buy pre-made compost for simplicity."),
        ],
        substrate_preference_ranking=["composted manure", "commercial mushroom compost"],
        contamination_risks=["Green mold (Trichoderma) on improperly composted substrate", "Cobweb mold on wet casing layers", "Bacterial blotch from over-watering the casing", "Competitor molds from inadequate Phase II pasteurization"],
    ),

    SpeciesProfile(
        id="wine_cap",
        common_name="Wine Cap / Garden Giant",
        scientific_name="Stropharia rugosoannulata",
        category="gourmet",
        substrate_types=["hardwood chips", "straw", "cardboard", "garden beds"],
        colonization_visual_description=(
            "Aggressive white mycelium. Burgundy-red caps with wine-colored ring on stem. "
            "Large mushrooms — caps can reach 6+ inches."
        ),
        contamination_risk_notes=(
            "Very aggressive colonizer. Tolerates non-sterile substrates. "
            "Can be grown in unsterilized wood chips or straw. Beginner-friendly."
        ),
        pinning_trigger_description=(
            "Temperature fluctuation + moisture. Very forgiving — will fruit "
            "when conditions are roughly right. No precise control needed."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=60, temp_max_f=80, humidity_min=70, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 30),
                notes="Very forgiving. Can colonize non-sterile wood chips. "
                      "Indoor bins or outdoor beds both work.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=75, humidity_min=80, humidity_max=95,
                co2_max_ppm=1500, co2_tolerance="high",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="passive", expected_duration_days=(7, 14),
                notes="Large mushrooms. Harvest when caps still convex. "
                      "Very wide temp tolerance.",
            ),
        },
        flush_count_typical=3,
        yield_notes="2-4 flushes. Large fruits. Also great as outdoor garden bed mushroom.",
        tags=["beginner", "forgiving", "large-fruits", "outdoor-capable"],
        tldr="Beginner OUTDOOR species. Layer spawn between soaked straw/wood chips. Cover with cardboard. Keep moist. Fruits naturally spring/fall with rain. Perennial bed produces for years. No indoor setup needed.",
        flavor_profile="Mild, potato-like with a slight wine/burgundy note. Large caps can reach 6+ inches. Texture similar to portobello. Great grilled or stuffed.",
        tek_guide=[
            TekStep(step_number=1, title="Bed Preparation", description="Prepare an outdoor bed of soaked hardwood chips or straw. Wine cap is primarily an outdoor species. Layer 4-6 inches of soaked wood chips in a shaded garden bed.", duration="2-3 hours", tips=["Wine cap is the ultimate beginner outdoor mushroom", "Shaded garden beds are ideal — under trees or alongside a fence"], common_mistakes=["Trying to grow exclusively indoors — wine cap is an outdoor species", "Using dry chips without soaking — soak for 24 hours"]),
            TekStep(step_number=2, title="Layered Spawning", description="Layer grain spawn between layers of soaked wood chips or straw: 2 inches chips, thin spawn layer, 2 inches chips, spawn, 2 inches chips. Cover with cardboard and mulch.", duration="1-2 hours", tips=["Cardboard cover retains moisture and protects the bed", "Water thoroughly after assembly"], common_mistakes=["Not layering spawn throughout — just putting it on top", "Forgetting the cardboard cover"]),
            TekStep(step_number=3, title="Colonization", description="Keep bed moist. Wine cap colonizes through the wood chips/straw over 2-4 weeks. White mycelium visible on chip surfaces indicates healthy colonization. Very forgiving species.", duration="14-30 days", tips=["Water like a garden bed during dry weather", "Wine cap is extremely forgiving — hard to fail with outdoor beds"], common_mistakes=["Letting the bed dry out completely", "Overwatering — the bed should be moist, not flooded"]),
            TekStep(step_number=4, title="Natural Fruiting", description="Wine cap fruits naturally in response to rain and temperature fluctuations in spring and fall. Large burgundy-red caps emerge from the bed. No manual intervention needed.", duration="Seasonal — spring and fall", tips=["Established beds are perennial and improve with age", "Check after rain events during spring and fall"], common_mistakes=["Expecting indoor-style controlled fruiting — this is an outdoor species", "Not checking regularly during fruiting season"]),
            TekStep(step_number=5, title="Harvest and Bed Maintenance", description="Harvest when caps are still convex. Large caps can reach 6+ inches. Add fresh wood chips or straw annually to feed the perennial bed.", duration="Ongoing annual maintenance", tips=["Annual topdressing of fresh wood chips keeps the bed productive for years", "The burgundy-red cap and wine-colored ring on the stem are the identifying features"], common_mistakes=["Not adding fresh chips annually — bed exhausts its food source", "Letting the bed be shaded out by plants growing over it"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Hardwood Chip Bed", ingredients={"hardwood wood chips": "5 cubic feet", "cardboard": "4x4 foot sheet"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=10, sterilization_method="pasteurize_cold_lime", sterilization_time_min=0, sterilization_temp_f=None, suitability="optimal", notes="Outdoor bed — no sterilization needed. Soak chips in water for 24 hours before use."),
        ],
        substrate_preference_ranking=["hardwood chips", "straw", "cardboard", "garden beds"],
        contamination_risks=["Slug and insect damage in outdoor beds", "Competitor fungi in outdoor environment — wine cap is aggressive and usually wins", "Drying out during summer months — needs regular watering", "Minimal contamination concerns — wine cap is one of the most forgiving species"],
    ),

    SpeciesProfile(
        id="almond_mushroom",
        common_name="Almond Mushroom / Himematsutake",
        scientific_name="Agaricus subrufescens",
        category="gourmet",
        substrate_types=["composted manure", "pasteurized straw with supplements"],
        colonization_visual_description=(
            "White mycelium on compost. Distinctive strong almond/anise aroma — "
            "this is normal and a sign of healthy growth."
        ),
        contamination_risk_notes=(
            "Compost substrate carries standard contamination risks. "
            "Moderate-slow colonizer. Good sterile technique needed."
        ),
        pinning_trigger_description=(
            "Casing layer + temperature drop + FAE. Similar to Agaricus bisporus. "
            "Casing layer required for fruiting."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=82, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(14, 28),
                notes="Compost-based. Likes warmer colonization than A. bisporus. "
                      "Strong almond scent is normal.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=68, temp_max_f=75, humidity_min=90, humidity_max=95,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Casing layer required. Temp drop from colonization triggers pinning.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=68, temp_max_f=78, humidity_min=85, humidity_max=92,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="Harvest when caps begin to open. Both gourmet and medicinal value.",
            ),
        },
        flush_count_typical=3,
        yield_notes="2-4 flushes. Strong almond flavor. Both gourmet and medicinal properties.",
        tags=["intermediate", "medicinal", "compost-substrate", "aromatic"],
        tldr="Intermediate. Composted substrate. Warm fruiter. Distinctive almond fragrance during cooking. Both gourmet and medicinal properties.",
        flavor_profile="Strong almond aroma when cooked — distinctive and delightful. Mild sweet flavor. Good sautéed or in soups. Also valued for medicinal beta-glucan content.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare composted manure or supplemented pasteurized straw. Similar substrate requirements to button mushroom but tolerates warmer conditions.", duration="4-12 hours pasteurization + composting time", tips=["Composted horse manure is the traditional substrate", "Warmer-loving than button mushroom — good for warm climates"], common_mistakes=["Using non-composted substrate — almond mushroom needs decomposed organics", "Insufficient pasteurization"]),
            TekStep(step_number=2, title="Spawning and Casing", description="Mix grain spawn with pasteurized compost at 10% rate. Apply casing layer (peat + vermiculite) after colonization. Casing layer is required.", duration="1-2 hours", tips=["Casing layer is required — same as button mushroom", "The distinctive almond aroma begins during colonization"], common_mistakes=["Skipping the casing layer", "Using non-pasteurized casing"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 75-82°F for 14-28 days. Warmer than button mushroom. Strong almond/anise aroma is normal and distinctive.", duration="14-28 days", tips=["The almond aroma is a reliable sign of healthy growth", "Warmer colonization than A. bisporus"], common_mistakes=["Being alarmed by the strong aroma — it is normal", "Colonizing too cool"]),
            TekStep(step_number=4, title="Fruiting", description="Temperature drop to 68-78°F, introduce FAE and 12/12 light. Mushrooms emerge through the casing layer.", duration="7-14 days per flush", tips=["Unlike button mushroom, almond mushroom benefits from light", "Both gourmet and medicinal value"], common_mistakes=["Treating exactly like button mushroom — almond mushroom likes warmer and lighter conditions", "Not maintaining casing moisture"]),
            TekStep(step_number=5, title="Harvest", description="Harvest when caps begin to open. Both the flavor (intense almond aroma) and medicinal properties make this a dual-purpose species.", duration="2-4 flushes", tips=["Harvest before caps fully flatten for best flavor", "Strong almond aroma intensifies when cooked"], common_mistakes=["Waiting until caps fully open — flavor peaks at the beginning of opening", "Not taking advantage of the drying well for storage"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Composted Manure", ingredients={"composted horse manure": "5 quarts", "straw": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="optimal", notes="Composted manure is the preferred substrate. Warmer conditions than A. bisporus."),
        ],
        substrate_preference_ranking=["composted manure", "pasteurized straw with supplements"],
        contamination_risks=["Bacterial contamination from warm, humid composted substrate", "Green mold during colonization phase", "Competitor molds on improperly composted substrate", "Warm growing conditions favor both beneficial growth and contaminants"],
    ),

    SpeciesProfile(
        id="maitake",
        common_name="Maitake / Hen of the Woods",
        scientific_name="Grifola frondosa",
        category="medicinal",
        substrate_types=["supplemented hardwood (oak)", "masters mix"],
        colonization_visual_description=(
            "White mycelium, slow to moderate. Dense colonization required. "
            "Forms overlapping grey-brown fan-shaped clusters (rosette)."
        ),
        contamination_risk_notes=(
            "Long colonization increases contamination risk. "
            "Trich is the primary threat. Good air quality critical."
        ),
        pinning_trigger_description=(
            "Cool temperatures + FAE + light. Temperature drop from colonization to fruiting. "
            "Fruits as a dense rosette cluster."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=77, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(30, 60),
                notes="Very long colonization. 4-8 weeks. Oak-based substrate preferred.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=55, temp_max_f=65, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(7, 14),
                notes="Temperature drop from colonization triggers pinning. Good FAE required.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=68, humidity_min=85, humidity_max=92,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="continuous", expected_duration_days=(14, 21),
                notes="Harvest when fan edges are still slightly curled. Don't let them flatten completely.",
            ),
        },
        flush_count_typical=2,
        yield_notes="1-3 flushes. Large rosette clusters. Both gourmet and medicinal value.",
        tags=["intermediate", "slow", "medicinal", "long-cycle", "gourmet-medicinal"],
        tldr="Advanced. Slow colonizer (30-60 days). Challenging to fruit consistently indoors. Grows in overlapping rosettes. Outdoor log/stump cultivation often more reliable. Large clusters possible (1+ lb).",
        flavor_profile="Rich, earthy, with a distinctive woodsy aroma. Firm frilly texture. Excellent roasted until crispy at edges. One of the premier gourmet mushrooms. Also known as 'Hen of the Woods.'",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust (oak preferred) or Masters Mix. Pressure sterilize at 15 PSI for 2.5 hours. Alternatively, inoculate oak logs or stumps outdoors.", duration="4-6 hours (blocks) or 2-3 hours (logs)", tips=["Oak is strongly preferred — maitake is an oak specialist in the wild", "Log/stump cultivation outdoors is often more reliable than indoor blocks"], common_mistakes=["Using non-oak hardwood — maitake strongly prefers oak", "Insufficient sterilization for supplemented sawdust"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized substrate bags with grain spawn at 10% rate using flow hood. For logs/stumps: drill holes and insert plug spawn.", duration="1-3 hours", tips=["Flow hood essential for blocks — maitake is not as aggressive as oysters", "For stumps, inoculate freshly cut oak stumps for best results"], common_mistakes=["Poor sterile technique for blocks — maitake's long colonization amplifies any error", "Using old or dried-out logs/stumps"]),
            TekStep(step_number=3, title="Extended Colonization", description="Incubate blocks at 68-77°F for 30-60 days. Very long colonization similar to shiitake. Logs take 6-12 months.", duration="30-60 days (blocks) or 6-12 months (logs)", tips=["Be prepared for shiitake-length colonization times", "Full colonization is critical before fruiting"], common_mistakes=["Premature fruiting — full colonization is essential", "Giving up too early with outdoor logs"]),
            TekStep(step_number=4, title="Fruiting Initiation", description="Cool to 55-65°F, introduce FAE and 12/12 light. Maitake forms as overlapping grey-brown fan-shaped clusters (rosette) from the block surface or stump.", duration="7-14 days to pins", tips=["Temperature drop from colonization triggers fruiting", "The rosette form is characteristic — overlapping fan-shaped brackets"], common_mistakes=["Insufficient temperature drop", "Not providing enough FAE during fruiting"]),
            TekStep(step_number=5, title="Harvest", description="Harvest when fan edges are still slightly curled. Do not let them flatten completely. Large rosette clusters can reach 1+ pound. Both gourmet and medicinal.", duration="14-21 days per flush", tips=["Harvest while edges are still curled for best texture", "Large clusters are possible from well-colonized blocks"], common_mistakes=["Waiting until fans fully flatten — tough texture", "Rough handling of the delicate rosette structure"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
            SubstrateRecipe(name="Masters Mix (50/50)", ingredients={"hardwood fuel pellets": "2.5 lbs", "soy hull pellets": "2.5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Industry standard. Higher yields than straw but requires pressure sterilization."),
        ],
        substrate_preference_ranking=["supplemented hardwood (oak)", "masters mix"],
        contamination_risks=["Trichoderma during 30-60 day colonization — very high exposure window", "Green mold on improperly sterilized supplemented substrate", "Bacterial contamination during long fruiting period", "Outdoor log cultivation exposed to competitor fungi and insects"],
    ),

    SpeciesProfile(
        id="reishi",
        common_name="Reishi",
        scientific_name="Ganoderma lucidum",
        category="medicinal",
        substrate_types=["supplemented hardwood", "grain"],
        colonization_visual_description=(
            "White mycelium, moderate-fast. May develop reddish-brown coloring as it matures. "
            "Aggressive colonizer when healthy."
        ),
        contamination_risk_notes=(
            "Very long fruiting cycle (90+ days total) increases contamination risk. "
            "Strong colonizer helps compete."
        ),
        pinning_trigger_description=(
            "CO2 level controls morphology: High CO2 = antler form, Low CO2 + FAE = conk/shelf form. "
            "Set growth_form in session config."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=85, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 21),
                notes="In-bag with filter patch. Likes warmth.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=75, temp_max_f=85, humidity_min=85, humidity_max=95,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=2, light_hours_off=22, light_spectrum="daylight_6500k",
                fae_mode="none", expected_duration_days=(30, 60),
                notes="ANTLER FORMATION: Keep CO2 >1500ppm intentionally. Restrict FAE. Minimal light.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=80, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(60, 90),
                notes="CONK FORMATION: Reduce CO2 with FAE for shelf/fan shape. Very long phase.",
            ),
        },
        flush_count_typical=1,
        yield_notes="Single growth cycle. Antler or conk form. Harvest when growth stops and lacquer hardens.",
        tags=["medicinal", "long-cycle", "co2-morphology", "antler", "conk"],
        tldr="Beginner medicinal. Can complete ENTIRE life cycle in an unopened bag (antler form). Antler = high CO2 (bag closed). Conk/shelf = low CO2 (bag opened, needs FAE). Very slow but very reliable. Low contamination risk. 90+ day cycle.",
        flavor_profile="Not eaten as food — extremely bitter and woody. Used for teas, tinctures, and dual extraction (water + alcohol). Dried and sliced or powdered.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust. Pressure sterilize at 15 PSI for 2.5 hours. Reishi can also be grown on grain. Sterilized substrate is essential.", duration="4-6 hours", tips=["Hardwood sawdust is preferred for traditional antler or conk form", "Reishi is surprisingly easy to colonize — one of the more reliable medicinal species"], common_mistakes=["Using straw — reishi needs supplemented hardwood or grain", "Insufficient sterilization"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized bags with grain spawn at 10% rate. Reishi colonizes aggressively — one of the more vigorous growers.", duration="1-2 hours", tips=["Reishi is an aggressive colonizer — less sterile technique stress than many medicinal species", "Can be grown in bags that are never opened for antler form"], common_mistakes=["Over-thinking the process — reishi is one of the easier medicinal species", "Not deciding on antler vs conk form before starting"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 75-85°F for 14-21 days. Reishi is a warm-loving species. Mycelium may develop reddish-brown coloring as it matures — this is normal.", duration="14-21 days", tips=["Reddish-brown mycelium coloring is normal for reishi", "Warm conditions speed colonization"], common_mistakes=["Mistaking normal brown coloring for contamination", "Too cool temperatures"]),
            TekStep(step_number=4, title="Growth Form Decision", description="CRITICAL DECISION: CO2 controls reishi morphology. ANTLER FORM: Keep bag sealed, high CO2 (>1500ppm), minimal light. Produces finger-like antlers. CONK FORM: Open bag, introduce FAE to lower CO2, add 12/12 light. Produces shelf/fan shape.", duration="30-90 days depending on form", tips=["Antler form is the easiest — literally leave the bag sealed and wait", "Conk form requires active management of FAE and humidity"], common_mistakes=["Not understanding that CO2 level determines the growth form", "Changing strategy mid-growth — pick antler or conk and commit"]),
            TekStep(step_number=5, title="Extended Fruiting", description="Reishi grows VERY slowly. Antler form develops over 30-60 days. Conk form over 60-90 days. The lacquer finish develops and hardens over time. Total cycle is 90+ days.", duration="30-90 days", tips=["Be patient — reishi is a slow grower but very reliable", "The glossy lacquer finish develops gradually and indicates maturity"], common_mistakes=["Harvesting too early before the lacquer hardens", "Expecting fast results — this is a 3+ month project"]),
            TekStep(step_number=6, title="Harvest and Processing", description="Harvest when growth stops and lacquer has hardened. Reishi is NOT eaten as food — it is extremely bitter and woody. Slice and dry for tea, tincture, or dual extraction.", duration="Drying: 24-48 hours at 130°F", tips=["Dual extraction (hot water + alcohol) captures the full range of medicinal compounds", "Dried reishi stores indefinitely"], common_mistakes=["Trying to eat reishi like a culinary mushroom — it is extremely bitter", "Not drying thoroughly before storage"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "grain"],
        contamination_risks=["Trichoderma during the 90+ day total growth cycle", "Bacterial contamination in conk form from high humidity FAE conditions", "Green mold on exposed surfaces during long fruiting", "Very long cycle means any contamination has maximum time to establish"],
    ),

    SpeciesProfile(
        id="cordyceps_militaris",
        common_name="Cordyceps militaris",
        scientific_name="Cordyceps militaris",
        category="medicinal",
        substrate_types=["brown rice"],
        colonization_visual_description=(
            "White mycelium on rice substrate. Slower than wood-lovers. "
            "Uniform colonization important for even fruiting."
        ),
        contamination_risk_notes=(
            "Rice substrate is nutrient-rich — higher contamination risk. "
            "Sterile technique critical. Green mold and bacteria main threats."
        ),
        pinning_trigger_description=(
            "Blue light (440-460nm) + cold drop + FAE. "
            "Standard daylight is insufficient — must have blue spectrum."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=68, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", expected_duration_days=(14, 21),
                notes="In sealed container. Brown rice substrate. Complete darkness.",
            ),
            GrowPhase.PRIMORDIA_INDUCTION: PhaseParams(
                temp_min_f=60, temp_max_f=65, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="blue_450nm",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(7, 14),
                notes="CRITICAL: Requires blue 440-460nm light. Standard daylight insufficient.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=60, temp_max_f=68, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="moderate",
                light_hours_on=16, light_hours_off=8, light_spectrum="blue_450nm",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(30, 45),
                notes="16/8 blue light cycle. Track orange stromata saturation as quality indicator.",
            ),
        },
        flush_count_typical=1,
        yield_notes="1-2 flushes. Bright orange stromata. Harvest when growth stops. Dry immediately.",
        tags=["advanced", "medicinal", "blue-light", "rice-substrate"],
        tldr="Advanced. NOT a wood-lover — grows on grain + nutrient broth in jars. LIGHT IS CRITICAL (won't fruit without it, needs blue 450nm). Long fruiting cycle (4-6 weeks) but low maintenance. Single harvest. Dehydrate immediately at 131°F.",
        flavor_profile="Mild, slightly sweet, earthy. Both fruiting bodies and grain medium are consumed. Usually dried and powdered for supplements/tea. Valued for cordycepin content — athletic performance and energy.",
        tek_guide=[
            TekStep(step_number=1, title="Brown Rice Substrate Preparation", description="Cook brown rice until soft but not mushy. Mix with nutrient broth (potato dextrose or custom blend). Load into wide-mouth jars or polypropylene containers. Pressure sterilize at 15 PSI for 90 minutes.", duration="3-4 hours", tips=["Brown rice is the ONLY substrate used for cordyceps — this is unique in the species library", "Wide, flat containers produce better yield — more surface area for stromata"], common_mistakes=["Using any substrate other than brown rice — cordyceps is unique in this requirement", "Over-cooking rice until mushy — should retain individual grain structure"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate cooled rice containers with liquid culture using sterile technique. Cordyceps liquid culture must be maintained carefully — it loses vigor quickly.", duration="1 hour", tips=["Use fresh, vigorous liquid culture — cordyceps LC degrades faster than other species", "Flow hood or SAB is essential — rice is nutrient-rich and contamination-prone"], common_mistakes=["Using old liquid culture — cordyceps loses vigor rapidly in storage", "Non-sterile technique on nutrient-rich rice substrate"]),
            TekStep(step_number=3, title="Colonization (Dark Phase)", description="Incubate at 68-75°F in COMPLETE DARKNESS for 14-21 days. Even brief light exposure during colonization can trigger premature, weak fruiting.", duration="14-21 days", tips=["Complete darkness is essential during colonization — cover containers", "Even a brief light leak can trigger premature fruiting"], common_mistakes=["CRITICAL: Any light during colonization — triggers weak, premature fruiting", "Storing in a room with light leaks"]),
            TekStep(step_number=4, title="Blue Light Fruiting Trigger", description="CRITICAL: Cordyceps REQUIRES blue light (440-460nm) for fruiting. Standard daylight 6500K is INSUFFICIENT. Switch to 12/12 blue light cycle, drop temp to 60-65°F, introduce moderate FAE.", duration="7-14 days to first primordia", tips=["You MUST have a dedicated blue 450nm light source — daylight does not work", "A strip of blue LEDs is sufficient — does not need to be high-intensity"], common_mistakes=["CRITICAL: Using standard white/daylight LEDs — cordyceps will not fruit without blue spectrum", "Not cold-shocking — the temperature drop is also important"]),
            TekStep(step_number=5, title="Stromata Development", description="Increase light to 16/8 blue cycle (16 hours on, 8 off). Maintain 60-68°F with moderate FAE. Bright orange stromata (finger-like projections) develop over 4-6 weeks. Track orange saturation as quality indicator.", duration="30-45 days", tips=["The deeper/more saturated the orange color, the higher the cordycepin content", "16/8 light cycle during this phase (longer than fruiting for most species)"], common_mistakes=["Insufficient light duration — 16 hours is needed, not the standard 12", "Interrupting the blue light cycle"]),
            TekStep(step_number=6, title="Harvest and Drying", description="Harvest when stromata growth stops and tips begin to swell (spore formation). Both the orange stromata AND the colonized rice medium are consumed/processed. Dry immediately at 131°F.", duration="Dry at 131°F for 8-12 hours", tips=["Both the orange fingers and the rice base have medicinal value", "Dry at exactly 131°F (55°C) — preserves cordycepin content"], common_mistakes=["Drying at too high a temperature — degrades cordycepin", "Not harvesting the rice substrate along with the stromata"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Brown Rice + Nutrient Broth", ingredients={"brown rice": "2 cups", "potato dextrose broth": "200ml", "nutritional yeast": "1 tablespoon"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="optimal", notes="Brown rice is the ONLY substrate for cordyceps. Wide flat containers maximize surface area for stromata."),
        ],
        substrate_preference_ranking=["brown rice"],
        contamination_risks=["Green mold on nutrient-rich rice substrate — contamination risk is high", "Bacterial contamination from wet rice conditions", "Rice is more contamination-prone than wood-based substrates", "Long fruiting cycle (30-45 days) gives contaminants time to establish"],
    ),

    SpeciesProfile(
        id="turkey_tail",
        common_name="Turkey Tail",
        scientific_name="Trametes versicolor",
        category="medicinal",
        substrate_types=["supplemented hardwood", "logs"],
        colonization_visual_description=(
            "White mycelium, moderate speed. Thin shelf-like fruit bodies with distinctive "
            "concentric color banding (brown, tan, grey, white edge)."
        ),
        contamination_risk_notes=(
            "Relatively forgiving species. Good competitor against contaminants. "
            "Standard sterile technique sufficient."
        ),
        pinning_trigger_description=(
            "FAE introduction + light. No cold shock required. "
            "Relatively easy to pin."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=70, temp_max_f=80, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(14, 21),
                notes="In-bag with filter patch. Moderate colonization speed.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=80, humidity_max=90,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(14, 28),
                notes="Track color banding as progress indicator. Forgiving conditions.",
            ),
        },
        flush_count_typical=3,
        yield_notes="2-4 flushes. Thin shelf fungi — low weight but high medicinal value. Dry for tea/extract.",
        tags=["beginner", "medicinal", "forgiving", "color-banding"],
        tldr="Beginner-Intermediate. Aggressive colonizer. Colorful concentric-zoned thin brackets. Very photosensitive — light influences color banding. Too tough to eat directly. Used for tea/tincture/powder.",
        flavor_profile="Not eaten directly — too tough and leathery. Simmered for tea, dried and powdered, or made into tincture. Among the most-researched medicinal mushrooms (PSK/PSP polysaccharides for immune support).",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust. Pressure sterilize at 15 PSI for 2.5 hours. Turkey tail can also be grown on hardwood logs outdoors.", duration="4-6 hours (sawdust) or log inoculation", tips=["Turkey tail is one of the most forgiving medicinal species", "Log cultivation is reliable and low-maintenance for outdoor growing"], common_mistakes=["Using straw alone — hardwood is preferred", "Over-supplementing substrate — turkey tail does not need much"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized bags or logs with grain/plug spawn. Turkey tail is an aggressive colonizer.", duration="1-2 hours", tips=["Turkey tail is aggressive — similar vigor to oyster mushrooms", "Log inoculation is straightforward with plug spawn"], common_mistakes=["Over-thinking technique — turkey tail is forgiving", "Not sealing log plug holes with wax"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 70-80°F for 14-21 days. Turkey tail colonizes at moderate-good speed.", duration="14-21 days", tips=["Aggressive colonizer — relatively contamination-resistant", "Wide temperature tolerance for colonization"], common_mistakes=["Insufficient colonization time", "Temperature extremes"]),
            TekStep(step_number=4, title="Fruiting", description="Introduce FAE, 12/12 light. No cold shock needed. Turkey tail is very forgiving. Thin shelf-like brackets develop with characteristic concentric color banding.", duration="14-28 days per flush", tips=["Light significantly influences the color banding pattern — more light = more vivid bands", "The concentric color bands are the species' signature feature"], common_mistakes=["Insufficient light — reduces the color banding that indicates healthy growth", "Expecting thick fleshy mushrooms — turkey tail produces thin brackets"]),
            TekStep(step_number=5, title="Harvest and Processing", description="Turkey tail is too tough and leathery to eat directly. Harvest when brackets are mature with full color banding. Dry and grind for tea, tincture, or capsules.", duration="Drying: 6-12 hours at 130°F", tips=["Hot water extraction (simmer for 2+ hours) is the traditional preparation", "Among the most-researched medicinal mushrooms — PSK/PSP polysaccharides"], common_mistakes=["Trying to eat fresh — too tough", "Not drying/processing properly for medicinal use"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Hardwood Sawdust", ingredients={"hardwood sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="good", notes="80/20 sawdust to bran ratio. Pressure sterilization required due to supplementation."),
        ],
        substrate_preference_ranking=["supplemented hardwood", "logs"],
        contamination_risks=["Trichoderma is the main threat — standard for wood-loving species", "Competitor fungi on outdoor logs", "Bacterial contamination from over-wet substrate", "Generally low risk — turkey tail is one of the more contamination-resistant species"],
    ),

    SpeciesProfile(
        id="chaga",
        common_name="Chaga",
        scientific_name="Inonotus obliquus",
        category="medicinal",
        substrate_types=["supplemented birch hardwood", "birch sawdust"],
        colonization_visual_description=(
            "Very slow white-brown mycelium. In nature grows on birch trees over years. "
            "Indoor cultivation produces myceliated grain/substrate, not wild conks."
        ),
        contamination_risk_notes=(
            "Extremely long colonization = very high contamination risk. "
            "Laboratory-grade sterile technique required."
        ),
        pinning_trigger_description=(
            "Does NOT form traditional fruit bodies indoors. Cultivated for mycelium biomass "
            "or liquid culture extraction, not conk formation."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=70, temp_max_f=80, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(60, 120),
                notes="Extremely slow. 2-4 months for substrate colonization. "
                      "Indoor cultivation yields mycelium biomass, not wild-harvested conks.",
            ),
        },
        flush_count_typical=0,
        yield_notes="No traditional fruiting. Harvest is myceliated substrate for extraction. "
                    "Medicinal value from mycelium biomass.",
        tags=["advanced", "medicinal", "very-slow", "mycelium-harvest", "birch"],
        safety_warning="Note: Cultivated chaga (mycelium-on-grain) lacks the melanin and betulinic acid of wild-harvested chaga. Not consumed directly — used for tea and tinctures only.",
        tldr="NOT practically cultivatable. Forms sclerotia on living birch trees over 5-15+ years. 'Cultivated chaga' is mycelium-on-grain lacking the melanin and betulinic acid of wild chaga. Best sourced from sustainable wild harvest.",
        flavor_profile="Brewed as tea — mild vanilla/coffee-like flavor. Rich in melanin and betulinic acid (wild-harvested only). Ground into powder for brewing.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented birch hardwood sawdust. Pressure sterilize at 15 PSI for 2.5 hours. Note: Indoor cultivation produces mycelium biomass, NOT the wild conk.", duration="4-6 hours", tips=["Birch substrate is strongly preferred — chaga is a birch specialist", "Understand that cultivated chaga is fundamentally different from wild-harvested"], common_mistakes=["Expecting to produce wild-type conks indoors — not possible", "Using non-birch substrate"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized birch sawdust with grain spawn or liquid culture. Extremely slow growth ahead.", duration="1-2 hours", tips=["Use the freshest, most vigorous culture available", "Be prepared for a very long colonization"], common_mistakes=["Using weak or old cultures — chaga is slow enough as-is", "Non-sterile technique on a months-long project"]),
            TekStep(step_number=3, title="Extended Colonization", description="Incubate at 70-80°F for 60-120 DAYS. Chaga is one of the slowest-colonizing species. White-brown mycelium gradually spreads through birch substrate.", duration="60-120 days", tips=["This is a 2-4 month project minimum", "Some growers go 6+ months for maximum biomass"], common_mistakes=["Expecting results in weeks — chaga takes months", "Giving up too early"]),
            TekStep(step_number=4, title="Harvest (Mycelium Biomass)", description="Harvest the entire colonized substrate block as mycelium biomass. No traditional fruiting occurs indoors. Dry and process for tea or tincture.", duration="Harvest when fully colonized", tips=["The product is mycelium-on-substrate, not mushroom fruit bodies", "Dried mycelium is ground for tea or extracted"], common_mistakes=["Expecting mushroom fruiting — chaga does not produce fruiting bodies indoors", "Not understanding that cultivated chaga lacks the melanin of wild conks"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Birch Sawdust", ingredients={"birch sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Birch substrate preferred. Product is mycelium biomass, not wild-type conk."),
        ],
        substrate_preference_ranking=["supplemented birch hardwood", "birch sawdust"],
        contamination_risks=["Extremely high contamination risk due to 60-120 day colonization", "Green mold can take over during the months-long colonization", "Bacterial contamination from moisture accumulation over months", "Laboratory-grade sterile technique is not optional for chaga cultivation"],
    ),

    SpeciesProfile(
        id="meshima",
        common_name="Meshima / Sang Hwang",
        scientific_name="Phellinus linteus",
        category="medicinal",
        substrate_types=["supplemented hardwood (mulberry)", "hardwood sawdust"],
        colonization_visual_description=(
            "Slow-growing yellow-brown mycelium. Forms woody shelf-like brackets. "
            "Very slow fruiting — primarily cultivated for mycelium biomass."
        ),
        contamination_risk_notes=(
            "Extremely long cycle increases contamination risk. "
            "Laboratory-grade sterile technique required."
        ),
        pinning_trigger_description=(
            "FAE + light after extended colonization. Forms woody bracket fungi. "
            "Most cultivators harvest mycelium biomass rather than fruit bodies."
        ),
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=72, temp_max_f=82, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="passive", expected_duration_days=(30, 90),
                notes="Very slow colonizer. Primarily cultivated for mycelium biomass and extraction.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=68, temp_max_f=78, humidity_min=85, humidity_max=95,
                co2_max_ppm=1000, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                expected_duration_days=(60, 120),
                notes="Woody bracket formation. Extremely slow. Harvest mycelium if fruit body not forming.",
            ),
        },
        flush_count_typical=1,
        yield_notes="Single growth cycle. Woody bracket or mycelium biomass harvest. "
                    "Primarily valued for hot water extraction.",
        tags=["advanced", "medicinal", "very-slow", "bracket-fungus"],
        tldr="Advanced. Slow bracket fungus on hardwood. Long colonization (60-120+ days). Rare in cultivation. Primarily grown as mycelium for extraction.",
        flavor_profile="Not eaten directly. Used in teas and tinctures. Researched for immune-modulating polysaccharides.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare supplemented hardwood sawdust (mulberry preferred). Pressure sterilize at 15 PSI for 2.5 hours.", duration="4-6 hours", tips=["Mulberry sawdust is the traditional substrate for meshima", "Primarily cultivated for mycelium biomass extraction"], common_mistakes=["Using non-hardwood substrate", "Insufficient sterilization for the extremely long growth cycle"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized substrate with grain spawn or liquid culture. Very slow growth ahead.", duration="1-2 hours", tips=["Use vigorous fresh cultures", "Sterile technique is critical for the long cycle"], common_mistakes=["Non-sterile technique", "Old or weak cultures"]),
            TekStep(step_number=3, title="Extended Colonization", description="Incubate at 72-82°F for 30-90 days. Very slow colonizer.", duration="30-90 days", tips=["Patience is essential — meshima is very slow", "Most cultivators harvest mycelium rather than waiting for brackets"], common_mistakes=["Premature harvesting", "Temperature fluctuations"]),
            TekStep(step_number=4, title="Fruiting (Optional)", description="If attempting bracket formation: introduce FAE and 12/12 light after extended colonization. Woody brackets form extremely slowly (60-120 days).", duration="60-120 days", tips=["Most practical to harvest mycelium biomass instead of waiting for brackets", "Bracket formation is unreliable in cultivation"], common_mistakes=["Expecting fast bracket formation", "Not considering mycelium harvest as the primary product"]),
            TekStep(step_number=5, title="Harvest and Processing", description="Harvest mycelium biomass or brackets. Dry and process for hot water extraction. Valued for immune-modulating polysaccharides.", duration="Drying: 12-24 hours at 130°F", tips=["Hot water extraction is the standard preparation", "Research interest in immune-modulating properties"], common_mistakes=["Trying to eat directly — woody and inedible", "Not extracting properly"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Supplemented Mulberry Sawdust", ingredients={"mulberry sawdust": "4 lbs", "wheat bran": "1 lb"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Mulberry is the traditional substrate. Primarily cultivated for mycelium extraction."),
        ],
        substrate_preference_ranking=["supplemented hardwood (mulberry)", "hardwood sawdust"],
        contamination_risks=["Very high contamination risk from 30-90+ day colonization", "Green mold during extended growth periods", "Bacterial contamination from moisture over months", "Laboratory sterile technique required"],
    ),

    # ─── NEW SPECIES (MEDICINAL / NOVELTY) ─────────────────────────────
    SpeciesProfile(
        id="agarikon",
        common_name="Agarikon",
        scientific_name="Laricifomes officinalis",
        category="medicinal",
        substrate_types=["old-growth conifer sawdust", "supplemented sawdust"],
        colonization_visual_description="Extremely slow white mycelium. Months to fully colonize. Dense and cottony.",
        contamination_risk_notes="Very high contamination risk due to extremely long colonization. Sterile technique critical. Not practical for home cultivation of fruiting bodies.",
        pinning_trigger_description="Rarely fruits in cultivation. Primarily grown as mycelium-on-substrate for medicinal extraction.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=75, humidity_min=90, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(90, 365),
                notes="Extremely slow colonizer. Months to years. Mycelium harvest is the primary product.",
            ),
        },
        flush_count_typical=0,
        yield_notes="Mycelium biomass harvest only. Fruiting bodies not practical in cultivation. Used for medicinal extraction (tinctures, powders).",
        tags=["medicinal", "very-advanced", "mycelium-harvest", "rare"],
        tldr="Very advanced / research-level. Extremely slow (months to years). Old-growth conifer wood. Not practical for home cultivation. Primarily mycelium-on-substrate for medicinal extraction.",
        flavor_profile="Not eaten. Extremely rare. Used for medicinal extraction only. Paul Stamets has championed preservation efforts.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare old-growth conifer sawdust substrate. Pressure sterilize at 15 PSI for 2.5 hours. Agarikon is an extremely slow colonizer.", duration="4-6 hours", tips=["Old-growth conifer (spruce, fir) is the natural substrate", "This is a research-level project — not practical for home cultivation"], common_mistakes=["Expecting practical fruiting — agarikon takes months to years", "Using hardwood — this is a conifer specialist"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized substrate with liquid culture. Laboratory-grade sterile technique is essential.", duration="1-2 hours", tips=["Use the freshest possible culture — agarikon grows very slowly", "Flow hood is mandatory"], common_mistakes=["Any break in sterile technique — months of work at risk", "Using sub-optimal cultures"]),
            TekStep(step_number=3, title="Extended Colonization", description="Incubate at 65-75°F for 90-365+ DAYS. Agarikon is one of the slowest-growing fungi known. Mycelium harvest is the only practical product.", duration="90-365+ days", tips=["This is measured in months to years, not days", "Mycelium biomass is the realistic harvest goal"], common_mistakes=["Expecting any result in less than 3 months", "Not maintaining sterile conditions for the duration"]),
            TekStep(step_number=4, title="Harvest (Mycelium Only)", description="Harvest mycelium-on-substrate biomass. Fruiting bodies are not practical in cultivation. Process for medicinal extraction.", duration="When fully colonized", tips=["Paul Stamets has been championing agarikon preservation", "Used for medicinal tinctures and extracts"], common_mistakes=["Expecting fruit bodies — not practical", "Not processing properly for medicinal use"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Old-Growth Conifer Sawdust", ingredients={"conifer sawdust (spruce/fir)": "5 lbs"}, water_liters_per_liter_substrate=1.2, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=150, sterilization_temp_f=250, suitability="optimal", notes="Only practical as mycelium-on-substrate. Fruiting not achievable in cultivation."),
        ],
        substrate_preference_ranking=["old-growth conifer sawdust", "supplemented sawdust"],
        contamination_risks=["Extremely high contamination risk — 90-365+ day colonization", "Any contamination during the months/years of growth is catastrophic", "Laboratory-grade sterile technique is mandatory", "Not practical outside research laboratory settings"],
    ),

    SpeciesProfile(
        id="panellus_stipticus",
        common_name="Bioluminescent Bitter Oyster",
        scientific_name="Panellus stipticus",
        category="gourmet",  # categorized as gourmet for UI but NOT edible
        strain="Eastern North American (bioluminescent)",
        substrate_types=["hardwood chips", "hardwood sawdust", "hardwood logs", "oat flakes"],
        colonization_visual_description="Slow white mycelium on hardwood. Mycelium itself glows green in complete darkness. 75% hardwood chips / 25% oat flakes recommended.",
        contamination_risk_notes="Moderate risk. Slow colonizer means longer exposure window. Sterile technique important.",
        pinning_trigger_description="Fruiting triggers not well understood. Does not reliably respond to cold shock or light. Terrarium setups work best. Some sub-strains fruit more readily than others.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=80, humidity_min=85, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(28, 42),
                notes="Slow colonizer. 4-6 weeks. ONLY Eastern North American strains are bioluminescent.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=60, temp_max_f=75, humidity_min=85, humidity_max=95,
                co2_max_ppm=1500, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="passive", substrate_moisture="field_capacity",
                expected_duration_days=(14, 60),
                notes="Fruiting unpredictable. Small fan-shaped caps 1-3cm. Gills glow brightest in complete darkness. Allow 10+ min for eyes to adjust. NOT EDIBLE.",
            ),
        },
        flush_count_typical=1,
        yield_notes="NOT EDIBLE — grown for bioluminescence display only. Small fan/kidney-shaped fruiting bodies. Mycelium also glows on agar plates and colonized substrate.",
        tags=["novelty", "bioluminescent", "not-edible", "display"],
        edible=False,
        safety_warning="WARNING: NOT SAFE FOR HUMAN CONSUMPTION. This species is astringent and bitter. Grown for bioluminescence display only.",
        tldr="Easy to grow, moderate to fruit. ONLY Eastern North American strains glow. Mycelium AND fruiting bodies bioluminescent green in complete darkness. Terrarium approach works best. 4-6 week colonization on hardwood chips/oat flakes.",
        flavor_profile="NOT EDIBLE — astringent and bitter. Grown purely for bioluminescence display. Gills glow green in complete darkness (allow 10+ min for eyes to adjust).",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare 75% hardwood chips / 25% oat flakes mix. Sterilize in jars or bags. ONLY Eastern North American strains are bioluminescent.", duration="3-4 hours", tips=["CRITICAL: Verify your culture is Eastern North American origin — other strains do NOT glow", "Hardwood chips + oat flakes is the recommended substrate"], common_mistakes=["Using non-Eastern NA strains — they are not bioluminescent", "Using pure grain substrate — hardwood chips are preferred"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate sterilized substrate with liquid culture or agar wedge. Slow colonizer — 4-6 weeks ahead.", duration="1 hour", tips=["Agar plates of P. stipticus glow in complete darkness — a good way to verify bioluminescence", "Standard sterile technique required"], common_mistakes=["Not verifying bioluminescence on agar first", "Using non-sterile technique"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 65-80°F for 28-42 days. Slow colonizer. The mycelium itself glows in complete darkness — you can check during colonization.", duration="28-42 days", tips=["Check in COMPLETE darkness (10+ minutes for eye adjustment) — mycelium glows green", "The glow is dim — your eyes need full dark adaptation"], common_mistakes=["Not waiting long enough for eyes to adjust — the glow is subtle", "Expecting bright glow — it is dim and requires complete darkness"]),
            TekStep(step_number=4, title="Fruiting (Terrarium Approach)", description="Fruiting is unpredictable. Terrarium setup with high humidity works best. Small fan-shaped caps emerge. Both mycelium and gills glow.", duration="14-60 days (unpredictable)", tips=["Terrarium approach with high humidity is most reliable", "Fruiting may or may not occur — the glowing mycelium is the main attraction"], common_mistakes=["Expecting reliable fruiting — it is unpredictable", "Giving up on the display value of glowing mycelium if fruiting does not occur"]),
            TekStep(step_number=5, title="Display and Enjoyment", description="NOT EDIBLE. Display colonized jars or terrarium in a completely dark room. Allow 10+ minutes for eyes to adapt. The green glow is the reward.", duration="Ongoing display", tips=["Complete darkness required — any ambient light washes out the glow", "Makes an incredible living art piece or conversation starter"], common_mistakes=["Any ambient light — even phone screens ruin the effect", "Touching the substrate — mechanical damage can temporarily increase glow intensity"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Hardwood Chips + Oat Flakes", ingredients={"hardwood chips": "3 cups", "oat flakes": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="optimal", notes="75/25 hardwood to oat ratio. ONLY Eastern North American strains are bioluminescent."),
        ],
        substrate_preference_ranking=["hardwood chips", "hardwood sawdust", "hardwood logs", "oat flakes"],
        contamination_risks=["Green mold during slow 28-42 day colonization", "Bacterial contamination in humid terrarium conditions", "Slow colonization gives contaminants time to establish", "NOT EDIBLE — do not consume even if fruiting succeeds"],
    ),

    SpeciesProfile(
        id="neonothopanus_nambi",
        common_name="Tropical Glow Mushroom",
        scientific_name="Neonothopanus nambi",
        category="gourmet",  # categorized for UI but NOT edible
        substrate_types=["hardwood chips", "oat flakes"],
        colonization_visual_description="Slow mycelium growth. Tropical species — keep above 64°F at all times. Store cultures at 64°F, not refrigerated.",
        contamination_risk_notes="High risk due to slow colonization and tropical temperature requirements.",
        pinning_trigger_description="Very temperature-sensitive. Fluctuations cause aborts. Terrarium approach recommended.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=64, temp_max_f=77, humidity_min=85, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(28, 42),
                notes="75% hardwood chips / 25% oat flakes. Tropical — never below 64°F. Mechanical damage to mycelium causes luminescence spike lasting 3-5 days.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=68, temp_max_f=82, humidity_min=85, humidity_max=95,
                co2_max_ppm=1500, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="passive", substrate_moisture="field_capacity",
                expected_duration_days=(14, 60),
                notes="Fruiting unpredictable. Reported brighter bioluminescence than P. stipticus. NOT EDIBLE.",
            ),
        },
        flush_count_typical=1,
        yield_notes="NOT EDIBLE — grown for bioluminescence only. Reportedly brighter than P. stipticus. Mycena chlorophos is the brightest known species but extremely hard to source.",
        tags=["novelty", "bioluminescent", "not-edible", "tropical", "advanced"],
        edible=False,
        safety_warning="WARNING: NOT SAFE FOR HUMAN CONSUMPTION. This species is grown for bioluminescence display only.",
        tldr="Advanced tropical. Reportedly brighter than P. stipticus. Never below 64°F. Very temperature-sensitive — fluctuations cause aborts. Mechanical damage to mycelium causes luminescence spike for 3-5 days.",
        flavor_profile="NOT EDIBLE. Grown for bioluminescence only. Tropical species requiring warm stable temperatures.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare 75% hardwood chips / 25% oat flakes. Sterilize. Tropical species — NEVER below 64°F.", duration="3-4 hours", tips=["Tropical species — temperature sensitivity is the primary challenge", "Same substrate as P. stipticus works well"], common_mistakes=["Allowing temperature below 64°F at any point — can be fatal to the culture", "Using non-tropical room conditions"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate with liquid culture or agar. Store cultures at 64°F minimum — do NOT refrigerate.", duration="1 hour", tips=["Store all cultures above 64°F — standard refrigerator storage will kill it", "Reported brighter bioluminescence than P. stipticus"], common_mistakes=["CRITICAL: Refrigerating cultures or spawn — tropical species dies in cold", "Standard mushroom culture storage protocols do not apply"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 68-82°F for 28-42 days. Absolutely stable temperature is critical — fluctuations cause aborts.", duration="28-42 days", tips=["Temperature stability is more important than exact temperature", "Mechanical damage to mycelium causes a luminescence spike lasting 3-5 days"], common_mistakes=["Temperature fluctuations — more damaging than wrong temperature", "Storing near cold drafts or AC vents"]),
            TekStep(step_number=4, title="Fruiting (Terrarium)", description="Terrarium approach with stable warm conditions and high humidity. Fruiting is very unpredictable.", duration="14-60 days (very unpredictable)", tips=["The glowing mycelium is the main attraction — fruiting is a bonus", "Mechanical disturbance triggers temporary glow brightening"], common_mistakes=["Expecting reliable fruiting", "Temperature instability during fruiting attempts"]),
            TekStep(step_number=5, title="Display", description="NOT EDIBLE. Display in complete darkness. Reported brighter than P. stipticus.", duration="Ongoing", tips=["Gently tapping or disturbing the substrate triggers a 3-5 day glow spike", "Complete darkness required for viewing"], common_mistakes=["Any ambient light during viewing", "Consuming — NOT EDIBLE"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Hardwood Chips + Oat Flakes", ingredients={"hardwood chips": "3 cups", "oat flakes": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="optimal", notes="Same substrate as P. stipticus. CRITICAL: Never below 64°F."),
        ],
        substrate_preference_ranking=["hardwood chips", "oat flakes"],
        contamination_risks=["High risk from slow colonization in warm conditions", "Bacterial contamination from warm, humid environment", "Temperature sensitivity — fluctuations cause culture failure", "NOT EDIBLE — do not consume"],
    ),

    SpeciesProfile(
        id="pestalotiopsis_microspora",
        common_name="Polyurethane-Eating Fungus",
        scientific_name="Pestalotiopsis microspora",
        category="gourmet",  # categorized for UI but NOT edible — research organism
        substrate_types=["grain", "agar", "polyurethane plastic"],
        colonization_visual_description="Endophytic fungus. Grows as standard mycelium on grain/agar. Can survive without air or light.",
        contamination_risk_notes="Standard sterile technique. Requires plant host (English Ivy, Kudzu) for fruiting.",
        pinning_trigger_description="Does not produce traditional mushroom fruiting bodies without a plant host. Primarily a research organism.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=77, temp_max_f=86, humidity_min=80, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(14, 28),
                notes="Degrades polyurethane plastic in aerobic AND anaerobic conditions. Uses serine hydrolase enzyme. Yale University 2011 discovery.",
            ),
        },
        flush_count_typical=0,
        yield_notes="NOT EDIBLE — research/citizen science organism. Degrades polyurethane (insulation, foam, shoe soles). No traditional fruiting without plant host.",
        tags=["novelty", "research", "not-edible", "plastic-degradation", "citizen-science"],
        edible=False,
        safety_warning="WARNING: NOT SAFE FOR HUMAN CONSUMPTION. This is a research organism only. Do not ingest.",
        tldr="Research organism. Degrades polyurethane plastic in aerobic AND anaerobic conditions — only known fungus to do so. Does not produce traditional fruiting bodies without plant host. Citizen science potential.",
        flavor_profile="NOT EDIBLE — research organism only. Degrades polyurethane (insulation, foam, shoe soles). Yale University 2011 discovery.",
        tek_guide=[
            TekStep(step_number=1, title="Grain/Agar Preparation", description="Prepare standard grain jars or agar plates. Sterilize. This is a research organism — not a traditional mushroom cultivation.", duration="2-4 hours", tips=["This is a research/citizen science project, not food production", "Can survive without air or light — unique among cultivated fungi"], common_mistakes=["Expecting traditional mushroom fruiting bodies", "Treating this like standard mushroom cultivation"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate with culture. Standard sterile technique. This endophytic fungus requires a plant host for fruiting.", duration="1 hour", tips=["Sourcing cultures may be difficult — academic/research suppliers", "The plastic degradation ability is the interesting feature"], common_mistakes=["Expecting traditional fruiting without a plant host", "Not understanding the endophytic nature"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 77-86°F for 14-28 days. The organism colonizes grain/agar normally but has the unique ability to degrade polyurethane plastic.", duration="14-28 days", tips=["Can survive in aerobic AND anaerobic conditions", "Uses serine hydrolase enzyme to break down polyurethane"], common_mistakes=["Expecting visible plastic degradation in days — it is a slow process", "Not maintaining warm conditions"]),
            TekStep(step_number=4, title="Research/Observation", description="NOT EDIBLE — research organism only. Interesting for studying plastic degradation. Does not produce traditional fruiting bodies without a plant host (English Ivy, Kudzu).", duration="Ongoing observation", tips=["Citizen science potential for plastic degradation research", "Yale University 2011 discovery — Jonathan Russell"], common_mistakes=["CRITICAL: Consuming — NOT SAFE FOR HUMAN CONSUMPTION", "Expecting practical plastic cleanup at home scale"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Standard Grain", ingredients={"rye grain": "1 quart"}, water_liters_per_liter_substrate=0.5, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="optimal", notes="Research organism. Can also colonize polyurethane plastic as sole carbon source."),
        ],
        substrate_preference_ranking=["grain", "agar", "polyurethane plastic"],
        contamination_risks=["Standard grain contamination risks", "Warm conditions favor bacterial competitors", "NOT EDIBLE — safety concern if confused with food production", "Research organism — handle with appropriate caution"],
    ),

    SpeciesProfile(
        id="schizophyllum_commune",
        common_name="Split Gill Mushroom",
        scientific_name="Schizophyllum commune",
        category="gourmet",
        substrate_types=["hardwood sawdust", "hardwood chips", "dead wood"],
        colonization_visual_description="Aggressive white mycelium. Found on every continent except Antarctica. Very common in nature.",
        contamination_risk_notes="Low risk — extremely aggressive colonizer. One of the most common fungi on Earth.",
        pinning_trigger_description="Fruits readily on dead hardwood. Standard FAE and humidity triggers.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=65, temp_max_f=85, humidity_min=80, humidity_max=100,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(10, 21),
                notes="Very aggressive colonizer. Wide temperature tolerance.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=60, temp_max_f=80, humidity_min=80, humidity_max=95,
                co2_max_ppm=1500, co2_tolerance="moderate",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=30, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(7, 14),
                notes="Small fan-shaped brackets with split gills. Technically edible but tough/rubbery. Degrades polyethylene and phenolic resins. Eaten in some tropical cuisines.",
            ),
        },
        flush_count_typical=3,
        yield_notes="Low culinary value — tough and rubbery. Interesting for research (plastic degradation, genetics — 23,328 mating types). Eaten in some tropical regions.",
        tags=["novelty", "research", "plastic-degradation", "easy"],
        safety_warning="Technically edible but very tough and rubbery. Primarily of interest for research purposes.",
        tldr="Easy. Most common fungus on Earth — found on every continent except Antarctica. Aggressive colonizer. Degrades polyethylene and phenolic resins. 23,328 mating types (most of any organism).",
        flavor_profile="Technically edible but tough and rubbery. Eaten in some tropical cuisines. Primarily of interest for research (plastic degradation, genetics).",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare hardwood sawdust or chips. Minimal preparation needed — this is one of the most aggressive colonizers on Earth. Found on every continent except Antarctica.", duration="2-4 hours", tips=["Extremely aggressive colonizer — one of the most common fungi on Earth", "Wide temperature tolerance (65-85°F)"], common_mistakes=["Over-preparing substrate — this species colonizes almost anything", "Over-thinking the process — it is extremely easy to grow"]),
            TekStep(step_number=2, title="Inoculation", description="Inoculate with liquid culture, agar, or even wild specimens on cardboard. Very forgiving.", duration="30 minutes - 1 hour", tips=["Can be collected from the wild and transferred to culture easily", "23,328 mating types — the most of any organism"], common_mistakes=["Over-complicating a simple species", "Not having a plan for what to do with it (primarily research interest)"]),
            TekStep(step_number=3, title="Colonization", description="Incubate at 65-85°F for 10-21 days. Very aggressive. Wide temperature tolerance.", duration="10-21 days", tips=["Very fast, very aggressive", "Excellent for demonstrating fungal biology"], common_mistakes=["Temperature extremes", "Not waiting for colonization"]),
            TekStep(step_number=4, title="Fruiting", description="Introduce FAE and light. Small fan-shaped brackets with split gills emerge. Technically edible but very tough and rubbery.", duration="7-14 days", tips=["The split gill structure is the diagnostic feature", "Degrades polyethylene and phenolic resins — research interest"], common_mistakes=["Expecting a culinary product — very tough texture", "Not appreciating the research value"]),
            TekStep(step_number=5, title="Observation/Research", description="Interesting for research: plastic degradation, 23,328 mating types (most of any organism), ubiquitous distribution. Technically edible in some tropical cuisines.", duration="Ongoing", tips=["Great educational organism", "Some tropical cuisines do eat S. commune when young and tender"], common_mistakes=["Dismissing as a weed fungus — it has fascinating biology", "Consuming older, tough specimens"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Hardwood Sawdust", ingredients={"hardwood sawdust": "5 lbs"}, water_liters_per_liter_substrate=1.0, spawn_rate_percent=10, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="optimal", notes="Colonizes almost any dead hardwood. Minimal substrate requirements."),
        ],
        substrate_preference_ranking=["hardwood sawdust", "hardwood chips", "dead wood"],
        contamination_risks=["Minimal contamination risk — one of the most aggressive colonizers on Earth", "May actually contaminate OTHER cultures if not properly contained", "Low culinary value — primarily research interest", "Some individuals have sensitivity — cook thoroughly if consuming"],
    ),

    SpeciesProfile(
        id="giant_puffball",
        common_name="Giant Puffball",
        scientific_name="Calvatia gigantea",
        category="gourmet",
        substrate_types=["grass/garden soil", "compost"],
        colonization_visual_description="Underground mycelium network in soil/grass. Not visible during colonization.",
        contamination_risk_notes="Outdoor cultivation only. Cannot be reliably grown indoors. Propagated by spore slurry over grass/garden beds.",
        pinning_trigger_description="Unpredictable. Fruits naturally in response to rain and temperature after mycelium establishes in soil. May take months to years.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=50, temp_max_f=80, humidity_min=60, humidity_max=100,
                co2_max_ppm=10000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="moist_soil",
                expected_duration_days=(60, 365),
                notes="Outdoor only. Slurry spores in water and pour over grass/garden beds. Keep area moist. Unreliable but spectacular when it works.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=55, temp_max_f=75, humidity_min=70, humidity_max=95,
                co2_max_ppm=10000, co2_tolerance="high",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="none", substrate_moisture="moist_soil",
                expected_duration_days=(7, 21),
                notes="Can exceed 20+ inches diameter. Edible ONLY when interior is pure white. Any yellow/green coloring = spores developing, no longer edible.",
            ),
        },
        flush_count_typical=1,
        yield_notes="Unreliable cultivation but massive yields when successful — a single puffball can exceed 10 lbs. Outdoor only. Slice and cook like bread/steak.",
        tags=["novelty", "outdoor", "advanced", "edible"],
        tldr="Advanced outdoor only. Propagate by spore slurry over grass/garden beds. Unreliable but spectacular — can exceed 20 inches diameter. Edible ONLY when interior is pure white.",
        flavor_profile="Mild, marshmallow-like when very fresh. Slice into steaks and pan-fry, or bread and deep-fry. Edible ONLY when interior is pure white — any yellow/green = developing spores, discard.",
        tek_guide=[
            TekStep(step_number=1, title="Spore Slurry Preparation", description="Outdoor-only species. Blend a portion of a mature puffball (interior still white) with non-chlorinated water to create a spore slurry. Some growers add a small amount of molasses.", duration="30 minutes", tips=["Only use puffball with PURE WHITE interior — any yellow/green means spores are too mature", "Non-chlorinated water is important — chlorine kills spores"], common_mistakes=["Using puffball with yellowing interior — spores are already dispersing", "Using chlorinated tap water"]),
            TekStep(step_number=2, title="Bed Inoculation", description="Pour spore slurry over prepared grass or garden bed area. Giant puffball grows in lawns and meadows naturally. Choose a partially shaded area with good soil.", duration="30 minutes", tips=["Partially shaded grass/lawn area is ideal", "Keep the area moist but not flooded"], common_mistakes=["Choosing a location with poor soil or full sun", "Paving or otherwise sealing the inoculation area"]),
            TekStep(step_number=3, title="Extended Underground Growth", description="Mycelium grows underground in the soil. This is completely invisible. May take months to years before any visible result. Keep the area moist.", duration="60-365+ days (completely unpredictable)", tips=["This is an outdoor long-term gamble — no guaranteed results", "Water during dry spells like you would a garden"], common_mistakes=["Digging up the area to check — disturbing the soil kills the mycelium", "Not watering during dry periods"]),
            TekStep(step_number=4, title="Fruiting (If You're Lucky)", description="Giant puffball appears as a white sphere in the grass after rain. Can exceed 20 inches in diameter. Completely unpredictable timing.", duration="7-21 days once visible", tips=["Appears after rain events — check regularly during growing season", "A single puffball can weigh 10+ pounds"], common_mistakes=["Not checking the area after rain", "Picking when too small — let them reach full size"]),
            TekStep(step_number=5, title="Harvest", description="CRITICAL: Only eat when interior is PURE WHITE. Any yellow or green coloring means spores are developing and it is no longer edible. Slice and cook like bread or steak.", duration="Harvest and cook immediately", tips=["Slice into 1/2-inch steaks and pan-fry — excellent flavor", "Interior must be absolutely uniformly white"], common_mistakes=["CRITICAL: Eating when interior shows any yellow or green", "Not using immediately — shelf life is very short"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="Grass/Garden Soil (Outdoor)", ingredients={"spore slurry": "from mature puffball", "non-chlorinated water": "1 gallon", "molasses": "1 tablespoon (optional)"}, water_liters_per_liter_substrate=0.0, spawn_rate_percent=0, sterilization_method="pasteurize_hot_water", sterilization_time_min=0, sterilization_temp_f=None, suitability="optimal", notes="Outdoor only. Spore slurry over grass/garden beds. Completely unpredictable results."),
        ],
        substrate_preference_ranking=["grass/garden soil", "compost"],
        contamination_risks=["Outdoor environment — no control over competing organisms", "Underground growth is invisible — no way to monitor", "Completely unpredictable results — may never fruit", "CRITICAL: Only eat when interior is pure white — yellow/green interior is not edible"],
    ),

    # ─── CUBENSIS STRAIN VARIANTS ───────────────────────────────────────
    SpeciesProfile(
        id="cubensis_z_strain",
        common_name="Z-Strain",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Z-Strain",
        substrate_types=["CVG", "rye grain", "manure-based compost", "BRF"],
        colonization_visual_description="VERY fast aggressive colonizer. Dense white rhizomorphic mycelium. One of the fastest cubensis strains.",
        contamination_risk_notes="Lower risk due to fast colonization speed. Standard cubensis contamination profile.",
        pinning_trigger_description="Standard cubensis — FAE introduction, 12/12 light, surface moisture conditions.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=78, temp_max_f=84, humidity_min=90, humidity_max=95,
                co2_max_ppm=5000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(5, 10),
                notes="Very fast colonizer — can colonize grain in 5-7 days. Higher colonization temp than standard cubensis (82-86°F optimal).",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=72, temp_max_f=79, humidity_min=90, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(7, 12),
                notes="Prolific dense canopies. High yield. Fast fruiting.",
            ),
        },
        flush_count_typical=4,
        yield_notes="High yield. Dense canopies. One of the most productive cubensis strains.",
        tags=["active", "cubensis", "beginner", "high-yield", "fast-colonizer"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Fast-colonizing cubensis strain — can colonize grain in 5-7 days at 78-84°F. Prolific dense canopies. High yield. One of the most productive cubensis strains with 4+ flushes.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "BRF"],
        contamination_risks=["Trichoderma (green mold) — most common threat, appears as white then green patches within 24-48 hours", "Cobweb mold — grey wispy overlay that spreads very fast, often responds to hydrogen peroxide spray", "Bacterial contamination — slimy/sour smell, often from wet spots or poor pasteurization", "Lipstick mold (Sporendonema) — pink/red spots, discard immediately"],
    ),

    SpeciesProfile(
        id="cubensis_mazatapec",
        common_name="Mazatapec",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Mazatapec",
        substrate_types=["CVG", "manure-based", "BRF"],
        colonization_visual_description="Slow-to-moderate white rhizomorphic mycelium. Classic Mexican landrace strain with long spiritual lineage.",
        contamination_risk_notes="Slower colonization increases contamination window slightly. Standard cubensis sterile technique applies.",
        pinning_trigger_description="Standard cubensis — FAE introduction, 12/12 light, high surface humidity. May be slower to pin than fast strains.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=81, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(12, 18),
                notes="Slow-moderate colonizer. Historic Mexican landrace strain.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=75, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(7, 14),
                notes="Medium-sized fruits with golden-brown caps. Standard harvest at veil break.",
            ),
        },
        flush_count_typical=3,
        yield_notes="Moderate yield. 3-4 flushes. Landrace strain with spiritual significance in Mazatec traditions.",
        tags=["active", "cubensis", "beginner", "landrace", "mexican"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Slow-to-moderate colonizer (12-18 days). Classic Mexican landrace strain with historic spiritual significance in Mazatec traditions. Standard fruiting conditions. Medium-sized golden-brown cap fruits. 3-4 flushes of moderate yield.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "BRF"],
        contamination_risks=["Trichoderma (green mold) — most common threat, appears as white then green patches within 24-48 hours", "Cobweb mold — grey wispy overlay that spreads very fast, often responds to hydrogen peroxide spray", "Bacterial contamination — slimy/sour smell, often from wet spots or poor pasteurization", "Lipstick mold (Sporendonema) — pink/red spots, discard immediately"],
    ),

    SpeciesProfile(
        id="cubensis_ecuadorian",
        common_name="Ecuadorian",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Ecuadorian",
        substrate_types=["CVG", "manure-based", "BRF"],
        colonization_visual_description="Moderate colonizer. Dense white rhizomorphic mycelium. Hardy and tolerant of suboptimal conditions.",
        contamination_risk_notes="Standard cubensis risk profile. Hardy strain with good contamination resistance.",
        pinning_trigger_description="Standard cubensis fruiting conditions. Dense clusters typical. Hardy and tolerant of minor environmental fluctuations.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=81, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(10, 16),
                notes="Moderate colonizer. Hardy and forgiving of environmental variation.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=75, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(7, 14),
                notes="Dense clusters. Large, meaty fruits. Good yields with forgiving conditions.",
            ),
        },
        flush_count_typical=4,
        yield_notes="Good yield. Dense clusters. Hardy and tolerant — good for beginners who want a forgiving strain.",
        tags=["active", "cubensis", "beginner", "hardy", "high-altitude-origin"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Moderate colonizer (10-16 days). Hardy high-altitude origin strain that tolerates suboptimal conditions well. Dense clusters of large meaty fruits. Forgiving for beginners. 4 flushes of good yield.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "BRF"],
        contamination_risks=["Trichoderma (green mold) — most common threat, appears as white then green patches within 24-48 hours", "Cobweb mold — grey wispy overlay that spreads very fast, often responds to hydrogen peroxide spray", "Bacterial contamination — slimy/sour smell, often from wet spots or poor pasteurization", "Lipstick mold (Sporendonema) — pink/red spots, discard immediately"],
    ),

    SpeciesProfile(
        id="cubensis_cambodian",
        common_name="Cambodian",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Cambodian",
        substrate_types=["CVG", "manure-based", "BRF"],
        colonization_visual_description="Fast colonizer. Dense white rhizomorphic mycelium. Originally collected near Angkor Wat, Cambodia.",
        contamination_risk_notes="Lower risk due to fast colonization speed. Standard cubensis sterile technique.",
        pinning_trigger_description="Standard cubensis fruiting conditions. Prolific pinner. Quick cycle from colonization to harvest.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=81, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(7, 12),
                notes="Fast colonizer. One of the quickest cycle cubensis strains.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=75, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(7, 12),
                notes="Prolific smaller fruits. High pin density. Quick flush-to-flush cycle.",
            ),
        },
        flush_count_typical=4,
        yield_notes="Prolific yield. Smaller individual fruits but high pin count. Fast cycle — good for multiple quick flushes.",
        tags=["active", "cubensis", "beginner", "fast-colonizer", "prolific"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Fast colonizer (7-12 days) originally collected near Angkor Wat, Cambodia. Prolific pinner with high pin density. Smaller individual fruits but very high counts. Quick flush-to-flush cycle — ideal for multiple rapid harvests. 4 flushes.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "BRF"],
        contamination_risks=["Trichoderma (green mold) — most common threat, appears as white then green patches within 24-48 hours", "Cobweb mold — grey wispy overlay that spreads very fast, often responds to hydrogen peroxide spray", "Bacterial contamination — slimy/sour smell, often from wet spots or poor pasteurization", "Lipstick mold (Sporendonema) — pink/red spots, discard immediately"],
    ),

    SpeciesProfile(
        id="cubensis_jack_frost",
        common_name="Jack Frost",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Jack Frost",
        substrate_types=["CVG", "manure-based", "BRF"],
        colonization_visual_description="Moderate colonizer. White/albino mutation with beautiful snow-white caps and blue-tinged gills at maturity.",
        contamination_risk_notes="Standard cubensis risk profile. Moderate contamination window.",
        pinning_trigger_description="Standard cubensis fruiting conditions. Beautiful white fruiting bodies. Harvest before gills fully blue — blue tinting indicates peak maturity.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=81, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(10, 16),
                notes="Moderate colonizer. Albino/white mutation strain.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=75, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(7, 14),
                notes="Snow-white caps with blue-tinged gills at maturity. High potency. Harvest when gills show blue tint.",
            ),
        },
        flush_count_typical=3,
        yield_notes="Good yield. Visually striking white fruits. Higher potency than standard cubensis strains.",
        tags=["active", "cubensis", "intermediate", "albino", "high-potency"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Moderate colonizer (10-16 days). White/albino mutation with snow-white caps and blue-tinged gills at maturity. Harvest when gills show blue tint. Higher potency than standard cubensis. 3 flushes of good yield.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "BRF"],
        contamination_risks=["Trichoderma (green mold) — most common threat, appears as white then green patches within 24-48 hours", "Cobweb mold — grey wispy overlay that spreads very fast, often responds to hydrogen peroxide spray", "Bacterial contamination — slimy/sour smell, often from wet spots or poor pasteurization", "Lipstick mold (Sporendonema) — pink/red spots, discard immediately"],
    ),

    SpeciesProfile(
        id="cubensis_enigma",
        common_name="Enigma",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Enigma",
        substrate_types=["CVG", "manure-based"],
        colonization_visual_description="Slow colonizer. Dense blobby mycelium. MUTATION — forms brain/coral-like blob structures instead of normal cap/stem mushrooms. Does NOT produce spores.",
        contamination_risk_notes="Higher risk due to slow colonization (21-35 days). Extended exposure window. Impeccable sterile technique required.",
        pinning_trigger_description="Does NOT form traditional fruiting bodies. Produces dense blob/brain-like masses. Harvest when growth slows and surface firms. Longer cycle than standard cubensis.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=81, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(21, 35),
                notes="Slow colonizer. Mutation — no spores produced. Must be propagated via liquid culture or agar transfer only.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=75, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(14, 28),
                notes="Forms dense blob/brain/coral structures, NOT normal cap+stem mushrooms. Harvest when growth slows and mass firms up. Very high potency.",
            ),
        },
        flush_count_typical=2,
        yield_notes="Moderate yield by weight. Dense blob structures. Very high potency. CLONE ONLY — no spores. Must propagate via LC or agar.",
        tags=["active", "cubensis", "intermediate-advanced", "mutation", "high-potency", "clone-only"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Slow colonizer (21-35 days). MUTATION — forms dense brain/coral-like blob structures instead of normal caps. CLONE ONLY (no spores). Harvest when growth slows and mass firms up. Very high potency. Must propagate via liquid culture or agar.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG or manure-based substrate. Standard cubensis pasteurization. Enigma is a mutation that does NOT produce spores — it can only be propagated via liquid culture or agar transfer.", duration="8-12 hours", tips=["CLONE ONLY — Enigma cannot be grown from spores because it does not produce them", "Source Enigma culture from a trusted cultivator — it can only be passed via LC or agar"], common_mistakes=["Trying to find Enigma spores — they do not exist", "Using unreliable culture sources"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Mix grain spawn with pasteurized substrate at 1:2 ratio. Enigma colonizes slowly (21-35 days).", duration="30 minutes", tips=["Higher spawn ratios help with slow colonization", "Ensure spawn is from verified Enigma genetics"], common_mistakes=["Low spawn ratio — Enigma is slow and needs good coverage", "Using contaminated or degraded cultures"]),
            TekStep(step_number=3, title="Extended Colonization", description="Seal tub at 75-81°F in darkness for 21-35 days. Enigma is a slow colonizer like PE varieties.", duration="21-35 days", tips=["Patience — Enigma takes 3-5 weeks to colonize", "Dense blobby mycelium growth is normal for Enigma"], common_mistakes=["Opening too early", "Insufficient sterile technique for the long colonization"]),
            TekStep(step_number=4, title="Fruiting (Blob Formation)", description="Introduce FAE, 12/12 light, 70-75°F. Instead of normal mushrooms, Enigma forms dense brain/coral-like blob structures. This is the intended morphology.", duration="14-28 days", tips=["The blob/brain/coral structures ARE the product — this is not a defect", "Growth is slow — the blobs build mass gradually over weeks"], common_mistakes=["Expecting normal cap-and-stem mushrooms — Enigma is a mutation", "Harvesting too early before blobs have built sufficient mass"]),
            TekStep(step_number=5, title="Harvest", description="Harvest when growth slows and the blob surface firms up. The dense structures are extremely potent. Dry immediately.", duration="When growth stops", tips=["Very high potency — dose carefully", "Dense blob structures dry well in a dehydrator"], common_mistakes=["Waiting too long after growth stops — can begin to rot", "Not understanding the extreme potency"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
        ],
        substrate_preference_ranking=["CVG", "manure-based"],
        contamination_risks=["Trichoderma — 21-35 day colonization creates a wide contamination window", "Clone-only propagation means culture degradation is a risk over time", "Blob structures can trap moisture and harbor bacteria", "Extended fruiting period increases contamination exposure"],
    ),

    SpeciesProfile(
        id="cubensis_amazonian",
        common_name="Amazonian",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Amazonian (PESA)",
        substrate_types=["CVG", "manure-based", "BRF"],
        colonization_visual_description="Moderate colonizer. Dense white rhizomorphic mycelium. Produces notably large, tall mushrooms.",
        contamination_risk_notes="Standard cubensis risk profile. Moderate contamination window.",
        pinning_trigger_description="Standard cubensis fruiting conditions. FAE + 12/12 light + surface evaporation. Produces large meaty fruits.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=81, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(10, 16),
                notes="Moderate colonizer. Produces large, tall fruiting bodies.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=75, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(7, 14),
                notes="Large, tall mushrooms — among the biggest cubensis fruits. Dense and meaty. Harvest at veil break.",
            ),
        },
        flush_count_typical=4,
        yield_notes="Good yield. Notably large fruits — tall stems and wide caps. One of the larger-fruiting cubensis strains.",
        tags=["active", "cubensis", "beginner-intermediate", "large-fruits"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Moderate colonizer (10-16 days). Produces notably large, tall mushrooms — among the biggest cubensis fruits. Standard fruiting conditions. Dense meaty fruits with wide caps. 4 flushes of good yield.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "BRF"],
        contamination_risks=["Trichoderma (green mold) — most common threat, appears as white then green patches within 24-48 hours", "Cobweb mold — grey wispy overlay that spreads very fast, often responds to hydrogen peroxide spray", "Bacterial contamination — slimy/sour smell, often from wet spots or poor pasteurization", "Lipstick mold (Sporendonema) — pink/red spots, discard immediately"],
    ),

    SpeciesProfile(
        id="cubensis_thai",
        common_name="Thai",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Thai (Koh Samui)",
        substrate_types=["CVG", "manure-based", "BRF"],
        colonization_visual_description="Fast colonizer. Dense white rhizomorphic mycelium. Subtropical origin from Koh Samui, Thailand. Thrives at higher temps.",
        contamination_risk_notes="Lower risk due to fast colonization. Standard cubensis sterile technique.",
        pinning_trigger_description="Standard cubensis fruiting conditions. Prolific and fast. Performs well at slightly warmer temperatures than most cubensis strains.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=77, temp_max_f=84, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(7, 12),
                notes="Fast colonizer. Subtropical origin — prefers warmer temps than standard cubensis.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=72, temp_max_f=79, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(7, 12),
                notes="Prolific fruiter. Medium-sized mushrooms. Multiple dense flushes.",
            ),
        },
        flush_count_typical=4,
        yield_notes="Prolific yield. Multiple dense flushes. Fast cycle — one of the better producing subtropical strains.",
        tags=["active", "cubensis", "beginner", "fast-colonizer", "subtropical"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Fast colonizer (7-12 days) from Koh Samui, Thailand. Subtropical origin — prefers warmer temps (77-84°F colonization). Prolific fruiter with medium-sized fruits. Multiple dense flushes. One of the better-producing subtropical strains with 4 flushes.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "BRF"],
        contamination_risks=["Trichoderma (green mold) — most common threat, appears as white then green patches within 24-48 hours", "Cobweb mold — grey wispy overlay that spreads very fast, often responds to hydrogen peroxide spray", "Bacterial contamination — slimy/sour smell, often from wet spots or poor pasteurization", "Lipstick mold (Sporendonema) — pink/red spots, discard immediately"],
    ),

    SpeciesProfile(
        id="cubensis_albino_a_plus",
        common_name="Albino A+",
        scientific_name="Psilocybe cubensis",
        category="active",
        strain="Albino A+",
        substrate_types=["CVG", "manure-based", "BRF"],
        colonization_visual_description="Moderate colonizer, slightly slower than standard cubensis. White/leucistic mutation — white or very pale caps. Dense mycelium growth.",
        contamination_risk_notes="Slightly longer colonization than standard cubensis increases exposure window marginally. Standard sterile technique applies.",
        pinning_trigger_description="Standard cubensis fruiting conditions. White/leucistic appearance — not a true albino (still produces some pigment). Harvest at veil break.",
        phases={
            GrowPhase.SUBSTRATE_COLONIZATION: PhaseParams(
                temp_min_f=75, temp_max_f=81, humidity_min=70, humidity_max=80,
                co2_max_ppm=2000, co2_tolerance="high",
                light_hours_on=0, light_hours_off=24, light_spectrum="none",
                fae_mode="none", substrate_moisture="field_capacity",
                expected_duration_days=(10, 18),
                notes="Slightly slower than standard cubensis. Leucistic mutation — white caps but technically not true albino.",
            ),
            GrowPhase.FRUITING: PhaseParams(
                temp_min_f=70, temp_max_f=75, humidity_min=85, humidity_max=95,
                co2_max_ppm=800, co2_tolerance="low",
                light_hours_on=12, light_hours_off=12, light_spectrum="daylight_6500k",
                fae_mode="scheduled", fae_interval_min=20, fae_duration_sec=300,
                substrate_moisture="field_capacity",
                expected_duration_days=(7, 14),
                notes="Distinctive white/pale appearance. Caramel spore print despite white caps. Good yields.",
            ),
        },
        flush_count_typical=4,
        yield_notes="Good yield comparable to standard cubensis. Distinctive white/leucistic appearance. Beginner-friendly despite unusual look.",
        tags=["active", "cubensis", "beginner-intermediate", "albino", "leucistic"],
        legal_disclaimer="LEGAL NOTICE: Psilocybin is a controlled substance in many jurisdictions. Check your local, state, and federal laws before cultivating this species. Possession, cultivation, and distribution may be illegal in your area. Some jurisdictions have decriminalized or legalized therapeutic use. Spore possession for microscopy is legal in most US states (exceptions: CA, ID, GA). This information is provided for educational and research reference only.",
        tldr="Slightly slower colonizer (10-18 days) than standard cubensis. White/leucistic mutation — white or very pale caps (not a true albino; still produces some pigment). Standard fruiting conditions. Caramel spore print despite white caps. 4 flushes of good yield comparable to standard cubensis.",
        flavor_profile="Active species are not primarily consumed for flavor. Typically dried and consumed in capsules, tea, or food preparations. Fresh specimens have a mild earthy/grain taste.",
        tek_guide=[
            TekStep(step_number=1, title="Substrate Preparation", description="Prepare CVG (coco coir, vermiculite, gypsum) by pasteurizing with boiling water in a bucket. Pour boiling water over the dry mix, seal the lid, and let it cool to room temperature (8-12 hours). Target field capacity moisture — squeeze a handful and only a few drops should fall.", duration="8-12 hours", tips=["Use a 5-gallon bucket with a gamma seal lid for consistent results", "Field capacity test: squeeze a fistful — only a few drops should fall"], common_mistakes=["Adding too much water — soggy substrate invites bacterial contamination", "Not waiting for full cool-down — heat kills spawn on contact"]),
            TekStep(step_number=2, title="Spawn to Substrate", description="Break up fully colonized grain spawn and mix thoroughly with cooled, pasteurized CVG substrate at a 1:2 to 1:4 spawn-to-substrate ratio in a monotub. Level the surface but do not pack down.", duration="30 minutes", tips=["Higher spawn ratios (1:2) colonize faster and resist contamination better", "Mix thoroughly for even colonization — no clumps of unmixed substrate"], common_mistakes=["Packing substrate too tightly — restricts airflow and causes pooling", "Using under-colonized grain spawn with visible uncolonized kernels"]),
            TekStep(step_number=3, title="Colonization", description="Seal the monotub (tape micropore tape over holes or leave lid latched with no FAE). Store in a dark location at 75-80°F. Do not open the tub during colonization. Wait for full surface colonization (7-14 days).", duration="7-14 days", tips=["Resist the urge to peek — every opening introduces contaminants", "A small amount of condensation on tub walls is normal and healthy"], common_mistakes=["Opening the tub during colonization to check progress", "Storing in direct sunlight or temperature-fluctuating locations"]),
            TekStep(step_number=4, title="Fruiting Introduction", description="Once the surface is 75-100% colonized, introduce fruiting conditions: crack the lid or open FAE holes, introduce 12/12 light cycle, and maintain surface moisture via misting and fanning 2-3x daily.", duration="5-10 days to first pins", tips=["Fan for 30 seconds after misting to promote surface evaporation", "Tiny water droplets on the surface (not pooling) are ideal"], common_mistakes=["Heavy direct misting on pins — causes aborts", "Insufficient FAE — high CO2 causes long leggy stems"]),
            TekStep(step_number=5, title="Fruiting and Harvest", description="Maintain fruiting conditions. Pins will develop into mature fruits in 5-10 days. Harvest individual mushrooms as their veils begin to tear — twist and pull gently or cut at the base with a clean blade.", duration="7-14 days per flush", tips=["Harvest just before or as the veil tears for best potency and appearance", "Harvest the entire flush at once if possible to encourage a uniform next flush"], common_mistakes=["Waiting too long — spore drop makes a mess and can suppress next flush", "Pulling too hard and damaging the substrate surface"]),
            TekStep(step_number=6, title="Dunk and Rest", description="After harvesting, soak the substrate block in cold water for 12-24 hours (dunk). Drain excess water, return to fruiting conditions. Next flush should appear in 7-14 days.", duration="12-24 hours soak + 7-14 days to next flush", tips=["Use cold water (40-50°F) for the dunk — acts as a cold shock trigger", "Weight down the substrate with a plate to keep it submerged"], common_mistakes=["Skipping the dunk — substrate dries out and yields drop sharply", "Soaking longer than 24 hours — waterlogged substrate invites bacteria"]),
        ],
        substrate_recipes=[
            SubstrateRecipe(name="CVG (Coco Coir, Vermiculite, Gypsum)", ingredients={"coco coir brick": "650g", "vermiculite": "2 quarts", "gypsum": "1 cup"}, water_liters_per_liter_substrate=0.8, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=90, sterilization_temp_f=170, suitability="optimal", notes="Most popular cubensis substrate. Cheap, reliable, low contamination risk."),
            SubstrateRecipe(name="Manure-Based (Horse/Cow)", ingredients={"aged horse manure": "5 quarts", "vermiculite": "2 quarts", "gypsum": "1 cup", "coco coir": "1 quart"}, water_liters_per_liter_substrate=0.9, spawn_rate_percent=10, sterilization_method="pasteurize_hot_water", sterilization_time_min=120, sterilization_temp_f=170, suitability="good", notes="Higher yields for many cubensis strains. Slightly more contamination risk than CVG."),
            SubstrateRecipe(name="BRF Cakes (Brown Rice Flour + Vermiculite)", ingredients={"brown rice flour": "2 cups", "vermiculite": "2 cups", "water": "1 cup"}, water_liters_per_liter_substrate=0.6, spawn_rate_percent=100, sterilization_method="pressure_sterilize", sterilization_time_min=90, sterilization_temp_f=250, suitability="acceptable", notes="Classic PF Tek. Simple but lower yield. Good for first-time growers."),
        ],
        substrate_preference_ranking=["CVG", "manure-based", "BRF"],
        contamination_risks=["Trichoderma (green mold) — most common threat, appears as white then green patches within 24-48 hours", "Cobweb mold — grey wispy overlay that spreads very fast, often responds to hydrogen peroxide spray", "Bacterial contamination — slimy/sour smell, often from wet spots or poor pasteurization", "Lipstick mold (Sporendonema) — pink/red spots, discard immediately"],
    ),
]
