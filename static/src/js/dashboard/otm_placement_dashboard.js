/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const EMPLOYMENT_LABELS = {
    jobseeker: "Jobseeker",
    employed: "Employed",
    intern: "Intern",
};
const QUALIFICATION_LABELS = {
    partly_qualified: "Partly Qualified",
    fully_qualified: "Fully Qualified",
    not_qualified: "Not Qualified",
};
const MODE_LABELS = {
    online: "Online",
    offline: "Offline",
};
const INTERVIEW_STATUS_LABELS = {
    scheduled: "Scheduled",
    confirmed: "Confirmed",
    completed: "Completed",
    cancelled: "Cancelled",
    no_show: "No Show",
    rescheduled: "Rescheduled",
};
const PLACEMENT_STATUS_LABELS = {
    not_placed: "Not Placed",
    interviewing: "Interviewing",
    selected: "Selected",
    placed: "Placed",
    declined: "Declined",
};

const CHART_COLORS = ["#16a34a", "#155e75", "#0ea5e9", "#f59e0b", "#dc2626", "#7c3aed", "#0f766e"];

export class OtmPlacementDashboard extends Component {
    static template = "otm_placement_management.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.candidateModel = "otm.placement.candidate";
        this.interviewModel = "otm.placement.mock.interview";
        this.recordModel = "otm.placement.record";

        this.state = useState({
            loading: true,
            error: null,
            cards: {
                totalCandidates: 0,
                jobseekers: 0,
                employed: 0,
                interns: 0,
                placed: 0,
                upcomingInterviews: 0,
                completedInterviews: 0,
            },
            byProgram: [],
            byEmployment: [],
            byQualification: [],
            byMode: [],
            byInterviewStatus: [],
            byPlacementStatus: [],
        });

        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const [
                totalCandidates,
                jobseekers,
                employed,
                interns,
                placed,
                upcomingInterviews,
                completedInterviews,
                byProgram,
                byEmployment,
                byQualification,
                byMode,
                byInterviewStatus,
                byPlacementStatus,
            ] = await Promise.all([
                this.orm.searchCount(this.candidateModel, []),
                this.orm.searchCount(this.candidateModel, [["employment_status", "=", "jobseeker"]]),
                this.orm.searchCount(this.candidateModel, [["employment_status", "=", "employed"]]),
                this.orm.searchCount(this.candidateModel, [["employment_status", "=", "intern"]]),
                this.orm.searchCount(this.candidateModel, [["stage", "=", "placement"]]),
                this.orm.searchCount(this.interviewModel, [["status", "in", ["scheduled", "confirmed"]]]),
                this.orm.searchCount(this.interviewModel, [["status", "=", "completed"]]),
                this.orm.formattedReadGroup(this.candidateModel, [], ["program_id"], ["__count"]),
                this.orm.formattedReadGroup(this.candidateModel, [], ["employment_status"], ["__count"]),
                this.orm.formattedReadGroup(this.candidateModel, [], ["qualification_status"], ["__count"]),
                this.orm.formattedReadGroup(this.interviewModel, [], ["mode"], ["__count"]),
                this.orm.formattedReadGroup(this.interviewModel, [], ["status"], ["__count"]),
                this.orm.formattedReadGroup(this.recordModel, [], ["placement_status"], ["__count"]),
            ]);

            this.state.cards = {
                totalCandidates,
                jobseekers,
                employed,
                interns,
                placed,
                upcomingInterviews,
                completedInterviews,
            };
            this.state.byProgram = this._normalize(byProgram, "program_id");
            this.state.byEmployment = this._normalize(byEmployment, "employment_status", EMPLOYMENT_LABELS);
            this.state.byQualification = this._normalize(byQualification, "qualification_status", QUALIFICATION_LABELS);
            this.state.byMode = this._normalize(byMode, "mode", MODE_LABELS);
            this.state.byInterviewStatus = this._normalize(byInterviewStatus, "status", INTERVIEW_STATUS_LABELS);
            this.state.byPlacementStatus = this._normalize(byPlacementStatus, "placement_status", PLACEMENT_STATUS_LABELS);
        } catch (error) {
            this.state.error = "Could not load dashboard data. Please refresh the page.";
            console.error(error);
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Turn a read_group() result into a uniform [{label, count, pct, color}]
     * list. Odoo's read_group count key changed across versions (used to be
     * `<field>_count`, is `__count` on newer server versions) so both are
     * checked defensively rather than assuming one.
     */
    _normalize(groups, field, labelMap) {
        const rows = (groups || [])
            .map((g) => {
                let key = g[field];
                let label = key;
                if (Array.isArray(key)) {
                    label = key[1];
                    key = key[0];
                } else if (labelMap && key in labelMap) {
                    label = labelMap[key];
                }
                const count = g.__count ?? g[`${field}_count`] ?? 0;
                return { key, label: label || "Not Set", count };
            })
            .filter((row) => row.count > 0);
        const max = Math.max(1, ...rows.map((r) => r.count));
        return rows
            .sort((a, b) => b.count - a.count)
            .map((row, idx) => ({
                ...row,
                pct: Math.round((row.count / max) * 100),
                color: CHART_COLORS[idx % CHART_COLORS.length],
            }));
    }

    openCandidates(domain) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Candidates",
            res_model: this.candidateModel,
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain || [],
            target: "current",
        });
    }

    openInterviews(domain) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Mock Interviews",
            res_model: this.interviewModel,
            view_mode: "list,calendar,form",
            views: [[false, "list"], [false, "calendar"], [false, "form"]],
            domain: domain || [],
            target: "current",
        });
    }
}

registry.category("actions").add("otm_placement_dashboard", OtmPlacementDashboard);
