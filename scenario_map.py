SCENARIO_MAP = {

    # ═══════════════════════════════════════════════════════════
    # DENTISTS (7 trigger kinds)
    # Voice: peer-clinical, trust-first, colleague-to-colleague
    # Use: technical terms (fluoride, caries, recall, JIDA, DCI)
    # Avoid: "cure", "guaranteed", "100% safe", promotional hype
    # ═══════════════════════════════════════════════════════════

    "research_digest": {
        "scope": "merchant",
        "hook_fields": [
            "category.digest[0].title",
            "category.digest[0].source",
            "category.digest[0].trial_n",
            "merchant.customer_aggregate.high_risk_adult_count",
            "merchant.identity.owner_first_name",
            "merchant.identity.locality",
        ],
        "cta_style": "open_ended",
        "send_as": "vera",
        "compulsion_lever": "specificity_as_proof",
        "framing": (
            "Open with the exact journal/source name + trial participant count. "
            "Connect the finding to the merchant's specific patient cohort "
            "(e.g., high_risk_adult_count). Offer to pull the abstract AND draft "
            "a patient-ed WhatsApp in one message. Voice: peer-clinical colleague. "
            "CRITICAL: Source citation (journal name + page) must appear verbatim "
            "at end of message — score is capped at 7/10 without it."
        ),
        "payload_keys": ["category", "top_item_id"],
    },

    "regulation_change": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.deadline_iso",
            "trigger.payload.top_item_id",
            "category.digest",
            "merchant.identity.name",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "loss_aversion_deadline",
        "framing": (
            "Lead with regulatory authority name + what changed + deadline date. "
            "Frame as 'this affects your clinic specifically.' Offer to draft a "
            "compliance checklist or patient notification. Urgent but not alarmist. "
            "Voice: precise, trustworthy. Include deadline date as a number. "
            "CRITICAL: Cite the regulatory source verbatim at end of message."
        ),
        "payload_keys": ["category", "top_item_id", "deadline_iso"],
    },

    "recall_due": {
        "scope": "customer",
        "hook_fields": [
            "trigger.payload.available_slots",
            "trigger.payload.due_date",
            "trigger.payload.service_due",
            "trigger.payload.last_service_date",
            "merchant.offers",
            "merchant.identity.owner_first_name",
            "merchant.identity.name",
            "customer.identity.name",
            "customer.identity.language_pref",
            "customer.relationship.last_visit",
        ],
        "cta_style": "multi_choice_slot",
        "send_as": "merchant_on_behalf",
        "compulsion_lever": "effort_externalization_slots",
        "framing": (
            "Speak as the merchant (NOT Vera). Reference months since last visit "
            "as a specific number. Offer EXACTLY 2 pre-formatted slot options "
            "(day + date + time). Include ₹ price from active offer. Honor customer "
            "language_pref (use hi-en mix if preference is 'hindi' or 'hi'). "
            "Warm-clinical tone — not cold or transactional."
        ),
        "payload_keys": ["service_due", "last_service_date", "due_date", "available_slots"],
    },

    "perf_dip": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.metric",
            "trigger.payload.delta_pct",
            "trigger.payload.vs_baseline",
            "merchant.performance.ctr",
            "category.peer_stats.avg_ctr",
            "merchant.identity.owner_first_name",
            "merchant.identity.locality",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "loss_aversion_peer_gap",
        "framing": (
            "Lead with the exact dip metric + percentage (e.g., 'calls dropped 40%'). "
            "Immediately compare vs peer baseline to contextualize (e.g., CTR 2.1% vs "
            "peer 3.0%). Reframe as actionable: 'Here is what 3 similar clinics did.' "
            "Offer one concrete next step. Voice: operator-to-operator, data-driven."
        ),
        "payload_keys": ["metric", "delta_pct", "window", "vs_baseline"],
    },

    "renewal_due": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.days_remaining",
            "trigger.payload.plan",
            "trigger.payload.renewal_amount",
            "merchant.performance.views",
            "merchant.performance.calls",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_confirm_cancel",
        "send_as": "vera",
        "compulsion_lever": "reciprocity_value_shown",
        "framing": (
            "Lead with days remaining + plan name. Reference actual performance "
            "metrics received this plan period (views, calls) to show value already "
            "received. Do NOT pressure — inform and let numbers speak. "
            "Include the renewal amount as a specific ₹ figure."
        ),
        "payload_keys": ["days_remaining", "plan", "renewal_amount"],
    },

    "cde_opportunity": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.credits",
            "trigger.payload.fee",
            "trigger.payload.digest_item_id",
            "category.digest",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "social_proof_peers",
        "framing": (
            "Reference the CDE opportunity + credit hours available + fee. "
            "Connect to a specific digest item relevant to their practice. "
            "Mention that other dentists in their area have enrolled. "
            "Voice: peer-professional encouragement."
        ),
        "payload_keys": ["digest_item_id", "credits", "fee"],
    },

    "competitor_opened": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.competitor_name",
            "trigger.payload.distance_km",
            "trigger.payload.their_offer",
            "trigger.payload.opened_date",
            "merchant.performance.ctr",
            "category.peer_stats.avg_ctr",
            "merchant.identity.owner_first_name",
            "merchant.identity.locality",
        ],
        "cta_style": "open_ended",
        "send_as": "vera",
        "compulsion_lever": "curiosity_competitive_intel",
        "framing": (
            "Lead with competitor name + exact distance in km + their offer price. "
            "Do NOT alarm — frame as market intelligence: 'thought you'd want to know.' "
            "Compare their CTR against merchant's to show relative position. "
            "Ask one genuine question: 'Want me to suggest a differentiation angle?'"
        ),
        "payload_keys": ["competitor_name", "distance_km", "their_offer", "opened_date"],
    },

    # ═══════════════════════════════════════════════════════════
    # SALONS (4 trigger kinds)
    # Voice: warm-practical, aspirational, visual, trend-sensitive
    # Use: seasonal refs, trend names, combo package framing
    # Avoid: clinical tone, overly transactional copy
    # ═══════════════════════════════════════════════════════════

    "festival_upcoming": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.festival",
            "trigger.payload.days_until",
            "trigger.payload.date",
            "merchant.offers",
            "merchant.performance.delta_7d",
            "merchant.identity.owner_first_name",
            "merchant.identity.locality",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "urgency_calendar_window",
        "framing": (
            "Open with festival name + exact days remaining. Reference any 7d "
            "performance spike if present. Connect to merchant's active offer or "
            "suggest one that fits the festival. Frame as a closing window: "
            "'bookings peak 5 days before.' Voice: warm, practical, fellow-operator."
        ),
        "payload_keys": ["festival", "date", "days_until", "category_relevance"],
    },

    "wedding_package_followup": {
        "scope": "customer",
        "hook_fields": [
            "trigger.payload.wedding_date",
            "trigger.payload.days_to_wedding",
            "trigger.payload.trial_completed",
            "trigger.payload.next_step_window_open",
            "merchant.offers",
            "merchant.identity.owner_first_name",
            "merchant.identity.name",
            "customer.identity.name",
            "customer.identity.language_pref",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "merchant_on_behalf",
        "compulsion_lever": "urgency_days_countdown",
        "framing": (
            "Speak as the salon (NOT Vera). Reference exact days to wedding date. "
            "Mention that trial is done and this is the skin-prep window. "
            "Offer a specific package from merchant.offers with price. "
            "Suggest a slot for the next session. Voice: warm, bridal-excited, "
            "but practical — not over-the-top. Honor customer language_pref."
        ),
        "payload_keys": ["wedding_date", "trial_completed", "days_to_wedding",
                         "next_step_window_open"],
    },

    "curious_ask_due": {
        "scope": "merchant",
        "hook_fields": [
            "merchant.identity.owner_first_name",
            "merchant.identity.name",
            "merchant.performance.views",
            "merchant.performance.calls",
            "merchant.customer_aggregate.lapsed",
        ],
        "cta_style": "open_ended",
        "send_as": "vera",
        "compulsion_lever": "reciprocity_genuine_question",
        "framing": (
            "Ask the merchant ONE genuine question about their business — "
            "something Vera is curious about and that will help her help them. "
            "Reference a real performance data point to show this isn't generic. "
            "Offer to turn their answer into a Google post or customer WhatsApp. "
            "Voice: warm, fellow-operator curiosity. No pitching."
        ),
        "payload_keys": ["ask_template", "last_ask_at"],
    },

    "winback_eligible": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.days_since_expiry",
            "trigger.payload.perf_dip_pct",
            "trigger.payload.lapsed_customers_added_since_expiry",
            "merchant.performance.views",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "loss_aversion_missed_customers",
        "framing": (
            "Lead with days since subscription expired + performance dip percentage "
            "since then. Then: lapsed customers added since expiry (showing what was "
            "missed). Offer a trial reactivation. Frame as 'here is what you've missed' "
            "not 'we want your money back.' Include all three numbers explicitly."
        ),
        "payload_keys": ["days_since_expiry", "perf_dip_pct",
                         "lapsed_customers_added_since_expiry"],
    },

    # ═══════════════════════════════════════════════════════════
    # RESTAURANTS (4 trigger kinds)
    # Voice: operator-to-operator, fast, data-driven, event-led
    # Use: covers, AOV, delivery mix, event references
    # Avoid: long copy, multi-step CTAs, generic food adjectives
    # ═══════════════════════════════════════════════════════════

    "ipl_match_today": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.match",
            "trigger.payload.venue",
            "trigger.payload.match_time_iso",
            "trigger.payload.is_weeknight",
            "trigger.payload.city",
            "merchant.offers",
            "merchant.identity.owner_first_name",
            "merchant.identity.locality",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "specificity_contrarian_data",
        "framing": (
            "CRITICAL CASE STUDY PATTERN: If is_weeknight is False (weekend match), "
            "recommend AGAINST a match-night promo — Saturday IPL shifts -12% "
            "restaurant covers (people watch at home). Instead recommend pushing "
            "the existing delivery offer. This contrarian, data-grounded angle is "
            "what case study #5 scored 50/50 on. Do not write a generic 'match day "
            "special' message. Include match name + time + the -12% weekend data point."
        ),
        "payload_keys": ["match", "venue", "city", "match_time_iso", "is_weeknight"],
    },

    "review_theme_emerged": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.theme",
            "trigger.payload.occurrences_30d",
            "trigger.payload.common_quote",
            "trigger.payload.trend",
            "merchant.performance.views",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "social_proof_review_data",
        "framing": (
            "Lead with the specific review theme + how many times it appeared in 30d. "
            "Quote one real snippet from common_quote if present. Offer to draft a "
            "response template or operational fix. Frame as opportunity not criticism."
        ),
        "payload_keys": ["theme", "occurrences_30d", "trend", "common_quote"],
    },

    "milestone_reached": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.milestone_value",
            "trigger.payload.metric",
            "trigger.payload.value_now",
            "trigger.payload.is_imminent",
            "merchant.identity.owner_first_name",
            "merchant.identity.name",
        ],
        "cta_style": "open_ended",
        "send_as": "vera",
        "compulsion_lever": "reciprocity_recognition",
        "framing": (
            "Celebrate the exact milestone number first — be specific, not generic. "
            "Then immediately suggest the logical next milestone or next step. "
            "Don't be saccharine — be genuinely useful. Voice: coach/operator. "
            "If is_imminent is True, add urgency: 'you're X away from the next milestone.'"
        ),
        "payload_keys": ["metric", "value_now", "milestone_value", "is_imminent"],
    },

    "active_planning_intent": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.intent_topic",
            "trigger.payload.merchant_last_message",
            "merchant.offers",
            "merchant.identity.owner_first_name",
            "merchant.identity.name",
            "merchant.identity.locality",
        ],
        "cta_style": "binary_confirm_cancel",
        "send_as": "vera",
        "compulsion_lever": "effort_externalization_draft_ready",
        "framing": (
            "CASE STUDY #6 PATTERN (scored 49/50): Merchant has expressed intent. "
            "Do NOT ask more qualifying questions. Produce a CONCRETE artifact: "
            "draft the actual message/post/plan inline in the response. "
            "Reference their last_message to show you read it. Reference specific "
            "locality name and offer. End with CONFIRM to send / CANCEL to revise. "
            "Maximum effort externalization: all work done, merchant just approves."
        ),
        "payload_keys": ["intent_topic", "merchant_last_message"],
    },

    # ═══════════════════════════════════════════════════════════
    # GYMS (5 trigger kinds)
    # Voice: coach-to-operator, motivational + data-backed
    # Use: retention %, lapsed counts, challenge framing
    # Avoid: guilt-shaming, unrealistic transformation claims
    # ═══════════════════════════════════════════════════════════

    "seasonal_perf_dip": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.delta_pct",
            "trigger.payload.season_note",
            "trigger.payload.is_expected_seasonal",
            "merchant.customer_aggregate.active",
            "merchant.customer_aggregate.lapsed",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "social_proof_industry_norm",
        "framing": (
            "CASE STUDY #7 PATTERN (scored 48/50): Reframe the dip as NORMAL seasonal "
            "pattern — 'every metro gym sees -25 to -35% in summer.' Include exact "
            "delta_pct from payload + season_note + active member count. "
            "Recommend: skip ad spend now, focus retention on active members. "
            "Offer to launch a 'summer attendance challenge' for retention. "
            "Voice: coach energy — data-backed, not alarming."
        ),
        "payload_keys": ["metric", "delta_pct", "window", "is_expected_seasonal",
                         "season_note"],
    },

    "customer_lapsed_hard": {
        "scope": "customer",
        "hook_fields": [
            "trigger.payload.days_since_last_visit",
            "trigger.payload.previous_focus",
            "trigger.payload.previous_membership_months",
            "merchant.offers",
            "merchant.identity.owner_first_name",
            "merchant.identity.name",
            "customer.identity.name",
            "customer.identity.language_pref",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "merchant_on_behalf",
        "compulsion_lever": "no_shame_low_friction",
        "framing": (
            "CASE STUDY #8 PATTERN (scored 50/50): Speak as the gym. NO GUILT, "
            "NO SHAME. Reference days since last visit as exact number. "
            "Reference their previous_focus (e.g., 'your evening yoga sessions'). "
            "Offer a new class or trial that connects to their focus area. "
            "Explicitly say: 'No judgment, no auto-charge.' One easy Yes/No. "
            "Honor language_pref. Voice: friendly coach, not disappointed trainer."
        ),
        "payload_keys": ["days_since_last_visit", "previous_focus",
                         "previous_membership_months"],
    },

    "trial_followup": {
        "scope": "customer",
        "hook_fields": [
            "trigger.payload.trial_date",
            "trigger.payload.next_session_options",
            "merchant.offers",
            "merchant.identity.owner_first_name",
            "customer.identity.name",
            "customer.identity.language_pref",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "merchant_on_behalf",
        "compulsion_lever": "effort_externalization_session_ready",
        "framing": (
            "Reference the specific trial date. Offer concrete next session options "
            "from payload. Keep it low-pressure: 'your spot is reserved if you want it.' "
            "Include offer price from merchant.offers. Honor language_pref."
        ),
        "payload_keys": ["trial_date", "next_session_options"],
    },

    "perf_spike": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.metric",
            "trigger.payload.delta_pct",
            "trigger.payload.likely_driver",
            "trigger.payload.vs_baseline",
            "merchant.offers",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "urgency_momentum_capture",
        "framing": (
            "Lead with the spike: exact metric + delta_pct. Reference likely_driver "
            "to show Vera did her homework. Suggest capitalizing NOW — offer a push "
            "or content post while momentum is live. Include vs_baseline for context. "
            "Voice: energetic, data-backed, operator tone."
        ),
        "payload_keys": ["metric", "delta_pct", "window", "vs_baseline", "likely_driver"],
    },

    "dormant_with_vera": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.days_since_last_merchant_message",
            "trigger.payload.last_topic",
            "merchant.performance.views",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "open_ended",
        "send_as": "vera",
        "compulsion_lever": "curiosity_gentle_restart",
        "framing": (
            "Gentle restart after silence. Reference exact days since last conversation "
            "and what the last topic was (last_topic). Pick one real performance data "
            "point (views) to show Vera has been watching. Ask one low-stakes question "
            "to re-engage. No pitching. Voice: warm, no pressure."
        ),
        "payload_keys": ["days_since_last_merchant_message", "last_topic"],
    },

    # ═══════════════════════════════════════════════════════════
    # PHARMACIES (4 trigger kinds)
    # Voice: utility-first, trustworthy, precise, compliance-safe
    # Use: molecule names, batch numbers, exact dates, dosage
    # Avoid: unsafe medical claims, aggressive promotional tone
    # ═══════════════════════════════════════════════════════════

    "supply_alert": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.molecule",
            "trigger.payload.affected_batches",
            "trigger.payload.manufacturer",
            "trigger.payload.alert_id",
            "merchant.customer_aggregate.active",
            "merchant.customer_aggregate.lapsed",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "urgency_compliance_critical",
        "framing": (
            "CASE STUDY #9 PATTERN (scored 50/50): URGENT. Lead with molecule name "
            "+ batch numbers + manufacturer. Reference count of affected customers "
            "from customer_aggregate. Offer to draft customer WhatsApp notification "
            "AND replacement workflow in one message. Voice: precise, trustworthy, "
            "compliance-first. Include alert_id as reference number."
        ),
        "payload_keys": ["alert_id", "molecule", "affected_batches", "manufacturer"],
    },

    "chronic_refill_due": {
        "scope": "customer",
        "hook_fields": [
            "trigger.payload.molecule_list",
            "trigger.payload.stock_runs_out_iso",
            "trigger.payload.delivery_address_saved",
            "merchant.offers",
            "merchant.identity.owner_first_name",
            "merchant.identity.name",
            "customer.identity.name",
            "customer.identity.language_pref",
        ],
        "cta_style": "binary_confirm_cancel",
        "send_as": "merchant_on_behalf",
        "compulsion_lever": "effort_externalization_refill_ready",
        "framing": (
            "CASE STUDY #10 PATTERN (scored 49/50): Speak as pharmacy. List exact "
            "molecule names from molecule_list. State exact run-out date from "
            "stock_runs_out_iso. Apply active offer (senior/delivery discount) "
            "with ₹ total + savings if calculable. If delivery_address_saved is True, "
            "mention 'same address as last time.' If customer language_pref is 'hi', "
            "open with 'Namaste.' Voice: precise, respectful, caring."
        ),
        "payload_keys": ["molecule_list", "last_refill", "stock_runs_out_iso",
                         "delivery_address_saved"],
    },

    "category_seasonal": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.season",
            "trigger.payload.trends",
            "trigger.payload.shelf_action_recommended",
            "merchant.offers",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "social_proof_seasonal_demand",
        "framing": (
            "Reference the season name + top health trends from payload. "
            "Suggest the specific shelf/display action from shelf_action_recommended. "
            "Offer to draft a customer awareness post or in-store notice. "
            "Voice: practical, trusted pharmacist peer."
        ),
        "payload_keys": ["season", "trends", "shelf_action_recommended"],
    },

    "gbp_unverified": {
        "scope": "merchant",
        "hook_fields": [
            "trigger.payload.estimated_uplift_pct",
            "trigger.payload.verification_path",
            "merchant.performance.views",
            "merchant.identity.owner_first_name",
        ],
        "cta_style": "binary_yes_no",
        "send_as": "vera",
        "compulsion_lever": "loss_aversion_missed_views",
        "framing": (
            "Lead with the estimated uplift % from verification. Show current views "
            "as baseline so merchant understands what X% more means in real numbers. "
            "Explain verification path is simple (N steps from payload). "
            "Voice: helpful, factual, low-pressure."
        ),
        "payload_keys": ["verified", "verification_path", "estimated_uplift_pct"],
    },
}
