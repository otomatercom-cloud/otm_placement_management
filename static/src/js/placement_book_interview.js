/* Otomater Placement - "Book Your Mock Interview" self-service page for a
   candidate who registered earlier (including one who chose "Not Right Now"
   at registration) and comes back later to book a slot. Vanilla JS, no
   framework dependency - mirrors placement.js's approach. */
(function () {
    "use strict";

    var app = document.getElementById("otm-book-interview-app");
    if (!app) {
        return;
    }

    var state = {
        candidateId: null,
        token: null,
        mode: null,
        selectedDate: null,
        selectedSlot: null,
        slotsByDate: {},
        // "book" = normal first-time/self-service booking (/placement/book).
        // "reattempt" = picking a slot to submit with a re-attempt request
        // (/placement/book-interview/request-reattempt) - not booked yet,
        // just sent for placement-manager approval.
        flow: "book",
    };

    var csrfToken = document.getElementById("otm_bi_csrf_token").value;

    function $(sel) { return app.querySelector(sel); }
    function $all(sel) { return Array.prototype.slice.call(app.querySelectorAll(sel)); }

    function showAlert(msg) {
        var alertEl = document.getElementById("otm-bi-alert");
        alertEl.textContent = msg;
        alertEl.classList.remove("d-none");
        alertEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    function hideAlert() {
        document.getElementById("otm-bi-alert").classList.add("d-none");
    }

    function goToStep(name) {
        $all(".otm-step").forEach(function (el) {
            el.classList.toggle("d-none", el.dataset.step !== name);
        });
        hideAlert();
    }

    function escapeHtml(str) {
        var div = document.createElement("div");
        div.textContent = str || "";
        return div.innerHTML;
    }

    function postJSON(url, payload) {
        return fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        }).then(function (resp) {
            return resp.json();
        });
    }

    function setButtonLoading(btn, loading, labelWhenIdle) {
        btn.disabled = loading;
        btn.innerHTML = loading ? '<span class="otm-spin"></span>Please wait…' : labelWhenIdle;
    }

    // --- STEP 1: lookup -----------------------------------------------
    $("#otm_bi_btn_lookup").addEventListener("click", function () {
        var phone = $("#otm_bi_phone").value.trim();
        var email = $("#otm_bi_email").value.trim();
        if (!phone || !email) {
            showAlert("Please enter both your WhatsApp number and email.");
            return;
        }
        var btn = $("#otm_bi_btn_lookup");
        setButtonLoading(btn, true, "Continue");
        postJSON("/placement/book-interview/lookup", {
            csrf_token: csrfToken, phone: phone, email: email,
        }).then(function (data) {
            setButtonLoading(btn, false, "Continue");
            if (!data.ok) {
                showAlert(data.error || "We couldn't find your registration.");
                return;
            }
            state.candidateId = data.candidate_id;
            state.token = data.token;
            state.flow = "book";
            document.getElementById("otm_bi_slots_title").textContent = "Choose Your Mock Interview Slot";
            document.getElementById("otm_bi_summary_title").textContent = "Booking Summary";
            document.getElementById("otm_bi_btn_confirm").innerHTML = "Confirm Booking";
            if (data.status === "scheduled") {
                document.getElementById("otm_bi_already_name").textContent = data.name;
                document.getElementById("otm_bi_view_existing").href = data.success_url;
                goToStep("already");
            } else if (data.status === "processing") {
                document.getElementById("otm_bi_processing_name").textContent = data.name;
                goToStep("processing");
            } else if (data.status === "completed") {
                document.getElementById("otm_bi_completed_name").textContent = data.name;
                goToStep("completed");
            } else {
                // "date_not_scheduled" (re-attempt approved) or "not_booked"
                // (fresh candidate) both proceed straight to slot booking.
                goToStep("mode");
            }
        }).catch(function () {
            setButtonLoading(btn, false, "Continue");
            showAlert("Something went wrong. Please try again.");
        });
    });

    // --- STEP 1b: pick a slot for a re-attempt request -------------------
    // Reuses the same mode -> slots -> summary steps as a normal booking;
    // only the final confirm step (below) branches on state.flow to POST
    // to request-reattempt instead of book, since this isn't a confirmed
    // booking yet - it's a slot choice sent for placement-manager approval.
    var reattemptBtn = document.getElementById("otm_bi_btn_request_reattempt");
    if (reattemptBtn) {
        reattemptBtn.addEventListener("click", function () {
            state.flow = "reattempt";
            document.getElementById("otm_bi_slots_title").textContent =
                "Choose Your Preferred Slot";
            document.getElementById("otm_bi_summary_title").textContent =
                "Re-attempt Request Summary";
            document.getElementById("otm_bi_btn_confirm").innerHTML = "Send for Approval";
            goToStep("mode");
        });
    }

    // --- STEP 2: mode ---------------------------------------------------
    $all(".otm-mode-card").forEach(function (card) {
        card.addEventListener("click", function () {
            $all(".otm-mode-card").forEach(function (c) { c.classList.remove("selected"); });
            card.classList.add("selected");
            card.querySelector("input").checked = true;
        });
    });

    document.getElementById("otm_bi_btn_back_mode").addEventListener("click", function () {
        goToStep("1");
    });

    document.getElementById("otm_bi_btn_mode_next").addEventListener("click", function () {
        var modeInput = app.querySelector('input[name="otm_bi_mode"]:checked');
        if (!modeInput) {
            showAlert("Please select Online or Offline.");
            return;
        }
        state.mode = modeInput.value;
        loadSlots();
        goToStep("slots");
    });

    // --- STEP 3: slots ----------------------------------------------------
    function loadSlots() {
        var grid = document.getElementById("otm_bi_slot_grid");
        var dateBar = document.getElementById("otm_bi_slot_dates");
        grid.innerHTML = '<div class="otm-slot-empty">Loading available slots…</div>';
        dateBar.innerHTML = "";
        fetch("/placement/slots?mode=" + encodeURIComponent(state.mode))
            .then(function (r) { return r.json(); })
            .then(function (slots) {
                state.slotsByDate = {};
                slots.forEach(function (s) {
                    state.slotsByDate[s.date] = state.slotsByDate[s.date] || [];
                    state.slotsByDate[s.date].push(s);
                });
                var dates = Object.keys(state.slotsByDate).sort();
                if (!dates.length) {
                    grid.innerHTML = '<div class="otm-slot-empty">No slots available right now. Our team will contact you to schedule.</div>';
                    return;
                }
                dates.forEach(function (d, idx) {
                    var chip = document.createElement("div");
                    chip.className = "otm-slot-date-chip" + (idx === 0 ? " active" : "");
                    chip.textContent = state.slotsByDate[d][0].date_label;
                    chip.dataset.date = d;
                    chip.addEventListener("click", function () {
                        $all(".otm-slot-date-chip").forEach(function (c) { c.classList.remove("active"); });
                        chip.classList.add("active");
                        renderSlotGrid(d);
                    });
                    dateBar.appendChild(chip);
                });
                renderSlotGrid(dates[0]);
            })
            .catch(function () {
                grid.innerHTML = '<div class="otm-slot-empty">Could not load slots. Please try again.</div>';
            });
    }

    function renderSlotGrid(date) {
        state.selectedDate = date;
        var grid = document.getElementById("otm_bi_slot_grid");
        grid.innerHTML = "";
        var slots = state.slotsByDate[date] || [];
        if (!slots.length) {
            grid.innerHTML = '<div class="otm-slot-empty">No slots for this date.</div>';
            return;
        }
        slots.forEach(function (slot) {
            var chip = document.createElement("div");
            chip.className = "otm-slot-chip" + (slot.available ? "" : " booked");
            chip.textContent = slot.time_label + (slot.available ? "" : " • Booked");
            if (slot.available) {
                chip.addEventListener("click", function () {
                    $all(".otm-slot-chip").forEach(function (c) { c.classList.remove("selected"); });
                    chip.classList.add("selected");
                    state.selectedSlot = slot;
                });
            }
            grid.appendChild(chip);
        });
    }

    document.getElementById("otm_bi_btn_back_slots").addEventListener("click", function () {
        goToStep("mode");
    });

    document.getElementById("otm_bi_btn_slots_next").addEventListener("click", function () {
        if (!state.selectedSlot) {
            showAlert("Please select a slot to continue.");
            return;
        }
        renderSummary();
        goToStep("summary");
    });

    // --- STEP 4: summary + confirm -----------------------------------------
    function renderSummary() {
        var el = document.getElementById("otm_bi_summary");
        var slot = state.selectedSlot;
        var html = "";
        html += "<div><strong>Mode:</strong> " + (state.mode === "online" ? "Online" : "Offline") + "</div>";
        html += "<div><strong>Date:</strong> " + slot.date_label + "</div>";
        html += "<div><strong>Time:</strong> " + slot.time_label + "</div>";
        if (state.mode === "offline" && slot.venue) {
            html += "<div><strong>Venue:</strong> " + escapeHtml(slot.venue) + "</div>";
        }
        if (slot.interviewer) {
            html += "<div><strong>Interviewer:</strong> " + escapeHtml(slot.interviewer) + "</div>";
        }
        el.innerHTML = html;
    }

    document.getElementById("otm_bi_btn_back_summary").addEventListener("click", function () {
        goToStep("slots");
    });

    document.getElementById("otm_bi_btn_confirm").addEventListener("click", function () {
        var btn = document.getElementById("otm_bi_btn_confirm");
        var isReattempt = state.flow === "reattempt";
        var idleLabel = isReattempt ? "Send for Approval" : "Confirm Booking";
        var url = isReattempt
            ? "/placement/book-interview/request-reattempt"
            : "/placement/book";
        setButtonLoading(btn, true, idleLabel);
        postJSON(url, {
            csrf_token: csrfToken,
            candidate_id: state.candidateId,
            token: state.token,
            slot_id: state.selectedSlot.id,
        }).then(function (data) {
            setButtonLoading(btn, false, idleLabel);
            if (!data.ok) {
                showAlert(data.error || "Sorry, this slot was just booked by another candidate. Please select another slot.");
                loadSlots();
                goToStep("slots");
                return;
            }
            if (isReattempt) {
                document.getElementById("otm_bi_success_icon").textContent = "⏳";
                document.getElementById("otm_bi_success_title").textContent =
                    "Your Slot Request Has Been Sent";
                var reqEl = document.getElementById("otm_bi_success_summary");
                var reqHtml = "";
                reqHtml += "<div><strong>Requested Date:</strong> " + state.selectedSlot.date_label + "</div>";
                reqHtml += "<div><strong>Requested Time:</strong> " + state.selectedSlot.time_label + "</div>";
                reqHtml += "<div><strong>Mode:</strong> " + (state.mode === "online" ? "Online" : "Offline") + "</div>";
                reqHtml += '<p class="text-muted mt-2">Our placement team will review this and confirm your slot.</p>';
                reqEl.innerHTML = reqHtml;
                document.getElementById("otm_bi_view_booking").classList.add("d-none");
                goToStep("success");
                return;
            }
            document.getElementById("otm_bi_success_icon").textContent = "🎉";
            document.getElementById("otm_bi_success_title").textContent =
                "Mock Interview Booked Successfully!";
            var el = document.getElementById("otm_bi_success_summary");
            var html = "";
            html += "<div><strong>Date:</strong> " + data.date_label + "</div>";
            html += "<div><strong>Time:</strong> " + data.time_label + "</div>";
            html += "<div><strong>Mode:</strong> " + (data.mode === "online" ? "Online" : "Offline") + "</div>";
            if (data.venue) { html += "<div><strong>Venue:</strong> " + escapeHtml(data.venue) + "</div>"; }
            el.innerHTML = html;
            var viewBtn = document.getElementById("otm_bi_view_booking");
            viewBtn.href = data.success_url;
            viewBtn.classList.remove("d-none");
            goToStep("success");
        }).catch(function () {
            setButtonLoading(btn, false, idleLabel);
            showAlert("Something went wrong. Please try again.");
        });
    });

    goToStep("1");
})();
