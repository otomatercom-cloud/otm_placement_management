/* Otomater Placement Registration - vanilla JS, no framework dependency. */
(function () {
    "use strict";

    var app = document.getElementById("otm-placement-app");
    if (!app) {
        return;
    }

    var TOTAL_FORM_STEPS = 5;
    var state = {
        step: 1,
        candidateId: null,
        token: null,
        mode: null,
        selectedDate: null,
        selectedSlot: null,
        slotsByDate: {},
    };

    var csrfToken = document.getElementById("otm_csrf_token").value;
    var years = JSON.parse(document.getElementById("otm_years_json").value || "[]");

    var yearSelect = document.getElementById("otm_admission_year");
    years.forEach(function (y) {
        var opt = document.createElement("option");
        opt.value = y;
        opt.textContent = y;
        yearSelect.appendChild(opt);
    });

    function $(sel) { return app.querySelector(sel); }
    function $all(sel) { return Array.prototype.slice.call(app.querySelectorAll(sel)); }

    function showAlert(msg) {
        var alertEl = document.getElementById("otm-alert");
        alertEl.textContent = msg;
        alertEl.classList.remove("d-none");
        alertEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    function hideAlert() {
        document.getElementById("otm-alert").classList.add("d-none");
    }
    function clearFieldErrors() {
        $all(".otm-error").forEach(function (el) { el.textContent = ""; });
    }

    function goToStep(n) {
        $all(".otm-step").forEach(function (el) {
            el.classList.toggle("d-none", parseInt(el.dataset.step, 10) !== n);
        });
        state.step = n;
        hideAlert();

        // progress indicator only covers the 5 registration-detail steps
        var pct = Math.min(n, TOTAL_FORM_STEPS) / TOTAL_FORM_STEPS * 100;
        document.getElementById("otm-progress-fill").style.width = pct + "%";
        $all(".otm-step-dot").forEach(function (dot) {
            var dn = parseInt(dot.dataset.step, 10);
            dot.classList.toggle("active", dn === n);
            dot.classList.toggle("done", dn < n);
        });
        document.getElementById("otm-progress").classList.toggle("d-none", n > TOTAL_FORM_STEPS);

        var nav = document.getElementById("otm-nav");
        var backBtn = document.getElementById("otm_btn_back");
        var nextBtn = document.getElementById("otm_btn_next");
        nav.classList.toggle("d-none", n === 8);
        backBtn.classList.toggle("d-none", n === 1 || n === 8);
        nextBtn.textContent = n === 7 ? "Confirm Booking" : (n === 6 ? "Continue" : "Continue");
        nextBtn.disabled = false;
    }

    document.getElementById("otm_employment_status").addEventListener("change", function (e) {
        document.getElementById("otm_employed_fields").classList.toggle(
            "d-none", e.target.value !== "employed"
        );
    });

    $all(".otm-mode-card").forEach(function (card) {
        card.addEventListener("click", function () {
            $all(".otm-mode-card").forEach(function (c) { c.classList.remove("selected"); });
            card.classList.add("selected");
            card.querySelector("input").checked = true;
        });
    });

    function validateStep(n) {
        clearFieldErrors();
        var ok = true;
        function fail(id, msg) {
            var errEl = document.getElementById("err_" + id);
            if (errEl) { errEl.textContent = msg; }
            ok = false;
        }
        if (n === 1) {
            if (!$("#otm_name").value.trim()) fail("name", "Please enter your name.");
            if (!$("#otm_phone").value.trim()) fail("phone", "Please enter a valid WhatsApp number.");
            var email = $("#otm_email").value.trim();
            if (!email || email.indexOf("@") === -1) fail("email", "Please enter a valid email address.");
        } else if (n === 2) {
            if (!$("#otm_program").value) fail("program_id", "Please select your program.");
        } else if (n === 5) {
            if (!app.querySelector('input[name="otm_mode"]:checked')) {
                fail("interview_preference", "Please select an interview preference.");
            }
        }
        return ok;
    }

    function collectPayload() {
        var checked = $all(".otm-support-checkbox:checked").map(function (c) { return c.value; });
        var modeInput = app.querySelector('input[name="otm_mode"]:checked');
        return {
            csrf_token: csrfToken,
            name: $("#otm_name").value.trim(),
            phone: $("#otm_phone").value.trim(),
            email: $("#otm_email").value.trim(),
            program_id: $("#otm_program").value,
            admission_year: $("#otm_admission_year").value,
            qualification_status: $("#otm_qualification_status").value,
            employment_status: $("#otm_employment_status").value,
            company_name: $("#otm_company_name").value,
            designation: $("#otm_designation").value,
            support_area_ids: checked,
            additional_support: $("#otm_additional_support").value,
            interview_preference: modeInput ? modeInput.value : null,
        };
    }

    function postJSON(url, payload) {
        return fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        }).then(function (resp) {
            return resp.json().then(function (data) {
                if (!resp.ok && !data) { throw new Error("Something went wrong. Please try again."); }
                return data;
            });
        });
    }

    function setLoading(loading) {
        var btn = document.getElementById("otm_btn_next");
        btn.disabled = loading;
        btn.innerHTML = loading ? '<span class="otm-spin"></span>Please wait…' :
            (state.step === 7 ? "Confirm Booking" : "Continue");
    }

    function submitRegistration() {
        setLoading(true);
        postJSON("/placement/register/submit", collectPayload()).then(function (data) {
            setLoading(false);
            if (!data.ok) {
                if (data.errors) {
                    Object.keys(data.errors).forEach(function (key) {
                        var el = document.getElementById("err_" + key);
                        if (el) { el.textContent = data.errors[key]; }
                    });
                }
                showAlert(data.error || "Please complete all required fields.");
                return;
            }
            state.candidateId = data.candidate_id;
            state.token = data.token;
            state.mode = data.mode;
            loadSlots();
            goToStep(6);
        }).catch(function () {
            setLoading(false);
            showAlert("Something went wrong. Please try again.");
        });
    }

    function loadSlots() {
        var grid = document.getElementById("otm_slot_grid");
        var dateBar = document.getElementById("otm_slot_dates");
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
        var grid = document.getElementById("otm_slot_grid");
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

    function renderSummary() {
        var el = document.getElementById("otm_summary");
        var slot = state.selectedSlot;
        var html = "";
        html += "<div><strong>Candidate:</strong> " + escapeHtml($("#otm_name").value) + "</div>";
        html += "<div><strong>Program:</strong> " + escapeHtml($("#otm_program").selectedOptions[0].textContent) + "</div>";
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

    function escapeHtml(str) {
        var div = document.createElement("div");
        div.textContent = str || "";
        return div.innerHTML;
    }

    function confirmBooking() {
        setLoading(true);
        postJSON("/placement/book", {
            csrf_token: csrfToken,
            candidate_id: state.candidateId,
            token: state.token,
            slot_id: state.selectedSlot.id,
        }).then(function (data) {
            setLoading(false);
            if (!data.ok) {
                showAlert(data.error || "Sorry, this slot was just booked by another candidate. Please select another slot.");
                loadSlots();
                goToStep(6);
                return;
            }
            var el = document.getElementById("otm_success_summary");
            var html = "";
            html += "<div><strong>Date:</strong> " + data.date_label + "</div>";
            html += "<div><strong>Time:</strong> " + data.time_label + "</div>";
            html += "<div><strong>Mode:</strong> " + (data.mode === "online" ? "Online" : "Offline") + "</div>";
            if (data.venue) { html += "<div><strong>Venue:</strong> " + escapeHtml(data.venue) + "</div>"; }
            el.innerHTML = html;
            document.getElementById("otm_view_booking").href = data.success_url;
            goToStep(8);
        }).catch(function () {
            setLoading(false);
            showAlert("Something went wrong. Please try again.");
        });
    }

    document.getElementById("otm_btn_next").addEventListener("click", function () {
        if (state.step <= TOTAL_FORM_STEPS) {
            if (!validateStep(state.step)) { return; }
            if (state.step === TOTAL_FORM_STEPS) {
                submitRegistration();
                return;
            }
            goToStep(state.step + 1);
        } else if (state.step === 6) {
            if (!state.selectedSlot) {
                showAlert("Please select a slot to continue.");
                return;
            }
            renderSummary();
            goToStep(7);
        } else if (state.step === 7) {
            confirmBooking();
        }
    });

    document.getElementById("otm_btn_back").addEventListener("click", function () {
        if (state.step === 7) { goToStep(6); }
        else if (state.step === 6) { goToStep(TOTAL_FORM_STEPS); }
        else if (state.step > 1) { goToStep(state.step - 1); }
    });

    goToStep(1);
})();
