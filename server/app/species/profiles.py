from .models import GrowPhase, PhaseParams, SpeciesProfile

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
    ),

    # ─── GOURMET SPECIES ────────────────────────────────────────────────
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
    ),

    # ─── MEDICINAL SPECIES ──────────────────────────────────────────────
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
    ),
]
