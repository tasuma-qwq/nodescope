/**
 * Clash IP Checker - Alpine.js Application
 */

function parseCandidateLine(line) {
    var parts = String(line || "").trim().split(/\s+/);
    if (!parts[0] || parts[0].indexOf("candidate:") !== 0) {
        return null;
    }
    var typIndex = parts.indexOf("typ");
    return {
        raw: line,
        foundation: parts[0].replace("candidate:", ""),
        component: parts[1] || "",
        protocol: parts[2] || "",
        priority: parts[3] || "",
        ip: parts[4] || "",
        port: parts[5] || "",
        type: typIndex >= 0 ? parts[typIndex + 1] : "unknown"
    };
}

function candidatesFromSdp(sdp) {
    var lines = String(sdp || "").split(/\r?\n/);
    var out = [];
    var i;
    for (i = 0; i < lines.length; i++) {
        if (lines[i].indexOf("a=candidate:") === 0) {
            var parsed = parseCandidateLine(lines[i].slice(2));
            if (parsed) {
                out.push(parsed);
            }
        }
    }
    return out;
}

function uniqueCandidates(list) {
    var seen = {};
    var out = [];
    var i;
    if (!list || !list.length) {
        return out;
    }
    for (i = 0; i < list.length; i++) {
        var c = list[i];
        if (!c || !c.ip) {
            continue;
        }
        var key = [c.ip, c.port, c.protocol, c.type].join("|");
        if (seen[key]) {
            continue;
        }
        seen[key] = true;
        out.push(c);
    }
    return out;
}

function gatherCandidates() {
    if (!window.isSecureContext) {
        return Promise.reject(new Error("WebRTC 检测需要 HTTPS 或 localhost。"));
    }
    if (!("RTCPeerConnection" in window)) {
        return Promise.reject(new Error("RTCPeerConnection 不可用，WebRTC 可能被禁用。"));
    }

    var found = [];
    var pc = new RTCPeerConnection({
        iceServers: [
            { urls: "stun:stun.l.google.com:19302" },
            { urls: "stun:stun.twilio.com:3478" }
        ],
        iceCandidatePoolSize: 1
    });

    pc.createDataChannel("ip-leak-test");

    pc.onicecandidate = function (event) {
        if (event.candidate && event.candidate.candidate) {
            var parsed = parseCandidateLine(event.candidate.candidate);
            if (parsed) {
                found.push(parsed);
            }
        }
    };

    return pc.createOffer().then(function (offer) {
        return pc.setLocalDescription(offer);
    }).then(function () {
        return new Promise(function (resolve) {
            var timeout = setTimeout(function () {
                resolve();
            }, 5500);
            pc.addEventListener("icegatheringstatechange", function () {
                if (pc.iceGatheringState === "complete") {
                    clearTimeout(timeout);
                    resolve();
                }
            });
        });
    }).then(function () {
        var sdp = pc.localDescription && pc.localDescription.sdp;
        var sdpCandidates = candidatesFromSdp(sdp);
        pc.close();
        return uniqueCandidates(found.concat(sdpCandidates));
    }).catch(function (err) {
        try {
            pc.close();
        } catch (e) {}
        return Promise.reject(err);
    });
}

function app() {
    return {
        // State
        yamlContent: '',
        config: {
            // 核心配置
            fast_mode: true,
            clash_api_url: 'http://127.0.0.1:9097',
            clash_api_secret: '',
            // 可选配置
            source: 'ping0',
            fallback: true,
            output_suffix: '_checked',
            selector_name: 'GLOBAL',
            headless: true,
            // 跳过关键词 (逗号分隔字符串)
            skip_keywords_str: '剩余,重置,到期,有效期,官网,网址,更新,公告,建议',
            // 多源交叉验证
            enable_multi_source: true,
            abuseipdb_key: '',
            ip2location_key: '',
            ipqs_key: '',
            dnsbl_enabled: true,
            dnsbl_zones_str: 'zen.spamhaus.org,bl.spamcop.net,dnsbl.sorbs.net,dnsbl.dronebl.org,b.barracudacentral.org,bl.blocklist.de,tor.dnsbl.sectoor.de',
            dns_leak_enabled: true,
            // AI/流媒体解锁探针（display-only，不计分）
            unlock_enabled: false,
            // IPv6 出口探测（display-only）
            ipv6_enabled: false
        },
        isRunning: false,
        showProgress: false,
        progress: 0,
        total: 0,
        currentNode: '',
        nodes: [],
        selected: [],
        sortByScore: null,
        error: '',

        // Edit state
        editingId: null,
        editValue: '',

        // Export state
        exportedYaml: '',
        exportFilename: '',
        exportUrl: '',
        subscribeUrl: '',

        // CodeMirror editor instance
        editor: null,
        exportEditor: null,
        eventSource: null,  // SSE connection reference

        // Initialize CodeMirror (only once)
        init() {
            this.loadHistory();

            // Prevent double initialization
            if (this.editor) return;

            const container = document.getElementById('yaml-editor');
            if (!container || container.querySelector('.CodeMirror')) return;

            this.editor = CodeMirror(container, {
                mode: 'yaml',
                theme: 'material-darker',
                lineNumbers: true,
                lineWrapping: false,
                placeholder: 'proxies:\n  - name: HK 01\n    type: ss\n    server: example.com\n    ...'
            });

            // Sync editor content to yamlContent and scroll to top after paste
            this.editor.on('change', (cm, change) => {
                this.yamlContent = this.editor.getValue();
                // Scroll to first line after paste operation (delay to ensure it happens after render)
                if (change.origin === 'paste' || change.origin === 'setValue') {
                    setTimeout(() => {
                        cm.scrollTo(0, 0);
                        cm.setCursor(0, 0);
                    }, 10);
                }
            });

            // Cleanup SSE on page unload to prevent connection leaks
            window.addEventListener('beforeunload', () => {
                if (this.eventSource) {
                    this.eventSource.close();
                    this.eventSource = null;
                }
            });
        },

        isRechecking: false,  // Exclusive lock for recheck
        webrtcRunning: false,
        webrtcMessage: '',
        webrtcError: '',

        historyItems: [],
        selectedHistory: null,
        historyLoading: false,
        historyError: '',

        trendOpen: false,
        trendNode: '',
        trendItems: [],
        trendLoading: false,
        trendError: '',

        // Methods
        async startCheck() {
            this.error = '';
            this.progress = 0;
            this.isRechecking = false;

            try {
                // Validate first
                const validateRes = await fetch('/api/validate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ yaml_content: this.yamlContent })
                });

                const validateData = await validateRes.json();
                if (!validateData.valid) {
                    this.error = validateData.error;
                    return;
                }

                // Start check
                const startRes = await fetch('/api/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        yaml_content: this.yamlContent,
                        config: this.config
                    })
                });

                if (!startRes.ok) {
                    if (startRes.status === 409) {
                        // Task is already running, just reconnect to SSE
                        this.isRunning = true;
                        this.showProgress = true;
                        this.connectSSE();
                        return;
                    }
                    const err = await startRes.json();
                    this.error = err.detail;
                    setTimeout(() => { this.error = null; }, 3000);
                    return;
                }

                const startData = await startRes.json();

                // Reset State for new run
                this.progress = 0;
                this.error = null;
                this.total = startData.total;

                this.isRunning = true;
                this.showProgress = true;

                // Fetch initial nodes (pending state) immediately
                try {
                    const nodesRes = await fetch('/api/nodes');
                    const nodesData = await nodesRes.json();
                    this.nodes = nodesData.nodes;
                    this.selected = this.nodes.map(n => n.id); // Default select all
                } catch (e) {
                    console.error("Initial nodes fetch failed", e);
                    this.nodes = [];
                    this.selected = [];
                }

                // Connect SSE
                this.connectSSE();
                this.loadHistory();

            } catch (e) {
                this.error = `请求失败: ${e.message}`;
            }
        },

        connectSSE() {
            // Close existing connection if any
            if (this.eventSource) {
                this.eventSource.close();
            }

            this.eventSource = new EventSource('/api/progress');

            this.eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === 'progress') {
                    this.progress = data.progress;
                    this.currentNode = data.node?.original_name || '';
                    if (data.node) {
                        const idx = this.nodes.findIndex(n => n.id === data.node.id);
                        if (idx !== -1) {
                            this.nodes[idx] = data.node;
                        } else {
                            this.nodes.push(data.node);
                            this.selected.push(data.node.id);
                        }
                    }
                } else if (data.type === 'update') {
                    // Handle single node update
                    const idx = this.nodes.findIndex(n => n.id === data.node.id);
                    if (idx !== -1) {
                        this.nodes.splice(idx, 1, data.node);
                    }
                } else if (data.type === 'complete') {
                    this.isRunning = false;
                    this.currentNode = '';
                    this.eventSource.close();
                    this.eventSource = null;
                    this.loadHistory();
                } else if (data.type === 'stopped') {
                    this.currentNode = '正在停止并恢复配置…';
                    this.eventSource.close();
                    this.eventSource = null;
                } else if (data.type === 'error') {
                    console.error('Node error:', data);
                }
            };

            this.eventSource.onerror = () => {
                if (!this.isRunning && this.eventSource) {
                    this.eventSource.close();
                    this.eventSource = null;
                }
            };
        },

        async recheckNode(node) {
            if (this.isRunning || this.isRechecking) return;

            this.isRechecking = true;
            const originalName = node.name;
            node.name = "⏳ 检测中..."; // Visual feedback

            try {
                const res = await fetch(`/api/nodes/${node.id}/recheck`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        config: this.config
                    })
                });

                if (!res.ok) {
                    const data = await res.json();
                    const errMsg = typeof data.detail === 'object' ? JSON.stringify(data.detail) : (data.detail || '重测失败');
                    alert(errMsg);
                    // Revert name on failure if not updated via SSE/Response
                    const idx = this.nodes.findIndex(n => n.id === node.id);
                    if (idx !== -1) this.nodes[idx].name = originalName;
                } else {
                    const data = await res.json();
                    const idx = this.nodes.findIndex(n => n.id === data.node.id);
                    if (idx !== -1) {
                        this.nodes.splice(idx, 1, data.node);
                    }
                }

            } catch (e) {
                alert('请求失败: ' + e);
                const idx = this.nodes.findIndex(n => n.id === node.id);
                if (idx !== -1) this.nodes[idx].name = originalName;
            } finally {
                this.isRechecking = false;
            }
        },

        async loadHistory() {
            this.historyError = '';
            this.historyLoading = true;
            try {
                const res = await fetch('/api/history');
                if (!res.ok) {
                    throw new Error('加载失败 ' + res.status);
                }
                const data = await res.json();
                this.historyItems = (data && data.items) ? data.items : [];
            } catch (e) {
                this.historyError = (e && e.message) ? e.message : String(e);
                this.historyItems = [];
            } finally {
                this.historyLoading = false;
            }
        },

        async openHistory(name) {
            this.historyError = '';
            try {
                const res = await fetch('/api/history/' + encodeURIComponent(name));
                if (!res.ok) {
                    this.historyError = res.status === 404 ? '快照不存在' : ('加载失败 ' + res.status);
                    this.selectedHistory = null;
                    return;
                }
                this.selectedHistory = await res.json();
            } catch (e) {
                this.historyError = (e && e.message) ? e.message : String(e);
                this.selectedHistory = null;
            }
        },

        closeHistory() {
            this.selectedHistory = null;
        },

        historySummaryText(summary) {
            if (!summary || typeof summary !== 'object') {
                return '';
            }
            const parts = [];
            if (summary.avg_pure !== undefined && summary.avg_pure !== null) {
                parts.push('均分 ' + summary.avg_pure);
            }
            if (summary.blacklisted) {
                parts.push('黑名单 ' + summary.blacklisted);
            }
            if (summary.dns_leak) {
                parts.push('DNS泄漏 ' + summary.dns_leak);
            }
            return parts.join(' · ');
        },

        histCell(value) {
            if (value === undefined || value === null || value === '') {
                return '—';
            }
            if (Array.isArray(value)) {
                return value.length ? value.join(', ') : '—';
            }
            if (typeof value === 'boolean') {
                return value ? '是' : '—';
            }
            return value;
        },

        histDnsbl(node) {
            if (!node || !node.dnsbl_blacklisted) {
                return '—';
            }
            if (Array.isArray(node.dnsbl_hits) && node.dnsbl_hits.length) {
                return node.dnsbl_hits.join(', ');
            }
            return '黑名单';
        },

        trendNodeOptions: function () {
            var nodes = this.nodes || [];
            var names = [];
            var i;
            for (i = 0; i < nodes.length; i++) {
                var n = nodes[i];
                var name = n && (n.original_name || n.name);
                if (!name) {
                    continue;
                }
                if (names.indexOf(name) === -1) {
                    names.push(name);
                }
            }
            return names;
        },

        loadTrend: async function () {
            this.trendOpen = true;
            this.trendError = '';
            var node = this.trendNode;
            if (!node) {
                var opts = this.trendNodeOptions();
                if (opts.length) {
                    node = opts[0];
                    this.trendNode = node;
                }
            }
            this.trendLoading = true;
            try {
                var res = await fetch('/api/history/trend?node=' + encodeURIComponent(node || ''));
                if (!res.ok) {
                    throw new Error('加载失败 ' + res.status);
                }
                var data = await res.json();
                this.trendItems = (data && data.items) ? data.items : [];
            } catch (e) {
                this.trendError = (e && e.message) ? e.message : String(e);
                this.trendItems = [];
            } finally {
                this.trendLoading = false;
            }
        },

        trendTimeLabel: function (t) {
            try {
                if (t === undefined || t === null) {
                    return '—';
                }
                var s = String(t);
                if (s.length >= 16) {
                    return s.slice(11, 16);
                }
                return s || '—';
            } catch (e) {
                return '—';
            }
        },

        trendCell: function (v) {
            if (v === undefined || v === null || v === '') {
                return '—';
            }
            return v;
        },

        trendChartPoints: function () {
            var items = this.trendItems || [];
            var pts = [];
            var i;
            for (i = 0; i < items.length; i++) {
                var item = items[i];
                if (!item) {
                    continue;
                }
                var score = item.risk_score;
                if (score === null || score === undefined || score === '') {
                    continue;
                }
                var num = Number(score);
                if (isNaN(num)) {
                    continue;
                }
                if (num < 0) {
                    num = 0;
                }
                if (num > 100) {
                    num = 100;
                }
                var ts = Date.parse(item.time);
                pts.push({
                    score: num,
                    t: isNaN(ts) ? null : ts,
                    label: this.trendTimeLabel(item.time)
                });
            }
            return pts;
        },

        trendMappedPoints: function () {
            var raw = this.trendChartPoints();
            var n = raw.length;
            var padX = 24;
            var padY = 16;
            var plotW = 600 - padX * 2;
            var plotH = 160 - padY * 2;
            var out = [];
            var i;
            var tmin = null;
            var tmax = null;
            for (i = 0; i < n; i++) {
                if (raw[i].t !== null) {
                    if (tmin === null || raw[i].t < tmin) {
                        tmin = raw[i].t;
                    }
                    if (tmax === null || raw[i].t > tmax) {
                        tmax = raw[i].t;
                    }
                }
            }
            var useTime = tmin !== null && tmax !== null && tmax > tmin;
            for (i = 0; i < n; i++) {
                var x;
                if (n === 1) {
                    x = padX + plotW / 2;
                } else if (useTime && raw[i].t !== null) {
                    x = padX + ((raw[i].t - tmin) / (tmax - tmin)) * plotW;
                } else {
                    x = padX + (i / (n - 1)) * plotW;
                }
                var y = padY + (1 - raw[i].score / 100) * plotH;
                out.push({
                    x: Math.round(x * 10) / 10,
                    y: Math.round(y * 10) / 10,
                    label: raw[i].label
                });
            }
            return out;
        },

        trendPolyline: function () {
            var pts = this.trendMappedPoints();
            if (pts.length < 2) {
                return '';
            }
            var parts = [];
            var i;
            for (i = 0; i < pts.length; i++) {
                parts.push(pts[i].x + ',' + pts[i].y);
            }
            return parts.join(' ');
        },

        trendCirclesHtml: function () {
            var pts = this.trendMappedPoints();
            var html = '';
            var i;
            for (i = 0; i < pts.length; i++) {
                html += '<circle cx="' + pts[i].x + '" cy="' + pts[i].y +
                    '" r="3.5" fill="#10b981"></circle>';
            }
            return html;
        },

        trendAxisHtml: function () {
            var pts = this.trendMappedPoints();
            if (pts.length < 2) {
                return '';
            }
            var html = '';
            var first = pts[0];
            var last = pts[pts.length - 1];
            html += '<text x="' + first.x + '" y="154" fill="#888888" font-size="11" text-anchor="start">' +
                this._trendEscape(first.label) + '</text>';
            if (last !== first) {
                html += '<text x="' + last.x + '" y="154" fill="#888888" font-size="11" text-anchor="end">' +
                    this._trendEscape(last.label) + '</text>';
            }
            return html;
        },

        _trendEscape: function (s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        },

        async stopCheck() {
            try {
                await fetch('/api/stop', { method: 'POST' });
                this.isRunning = false;
            } catch (e) {
                console.error('Stop failed:', e);
            }
        },

        // Selection
        selectAll() {
            this.selected = this.nodes.map(n => n.id);
        },

        selectNone() {
            this.selected = [];
        },

        toggleAll(e) {
            if (e.target.checked) {
                this.selectAll();
            } else {
                this.selectNone();
            }
        },

        // Edit
        startEdit(node) {
            this.editingId = node.id;
            this.editValue = node.name;
            this.$nextTick(() => {
                const input = document.querySelector('.inline-edit');
                if (input) input.focus();
            });
        },

        async saveEdit(node) {
            if (this.editValue.trim() && this.editValue !== node.name) {
                try {
                    await fetch(`/api/nodes/${node.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: this.editValue })
                    });
                    node.name = this.editValue;
                } catch (e) {
                    console.error('Save failed:', e);
                }
            }
            this.editingId = null;
        },

        cancelEdit() {
            this.editingId = null;
        },

        // Delete
        async deleteNode(node) {
            if (!confirm(`确定删除节点 "${node.original_name}"?`)) return;

            try {
                await fetch(`/api/nodes/${node.id}`, { method: 'DELETE' });
                this.nodes = this.nodes.filter(n => n.id !== node.id);
                this.selected = this.selected.filter(id => id !== node.id);
            } catch (e) {
                console.error('Delete failed:', e);
            }
        },

        latestCheckedIp() {
            var ip = '';
            var nodes = this.nodes || [];
            var i;
            for (i = 0; i < nodes.length; i++) {
                var n = nodes[i];
                if (!n || !n.ip) {
                    continue;
                }
                if (n.ip !== '❓' && n.ip !== '...' && n.ip !== 'N/A') {
                    ip = n.ip;
                }
            }
            return ip;
        },

        formatWebrtcResult(data) {
            var lines = [];
            if (!data) {
                return '';
            }
            var state = data.state || '';
            var leaked = data.leaked_public_ips || [];
            var priv = data.private_or_local || [];
            var mdns = data.mdns || [];
            var findings = data.findings || [];
            var i;
            var noCand = false;
            for (i = 0; i < findings.length; i++) {
                if (findings[i] && findings[i].id === 'webrtc_no_candidates') {
                    noCand = true;
                    break;
                }
            }
            if (state === 'public_ip_leak_detected') {
                lines.push('泄漏：浏览器暴露了与代理出口不同的公网 IP' + (leaked.length ? '（' + leaked.join(', ') + '）' : ''));
            } else if (state === 'webrtc_public_ip_matches_http_ip') {
                lines.push('无泄漏：WebRTC 出口与代理一致');
            }
            if (priv.length) {
                lines.push('私网 IP 暴露：' + priv.join(', '));
            }
            if (mdns.length) {
                lines.push('浏览器已启用 mDNS 遮蔽（' + mdns.join(', ') + '）');
            }
            if (noCand || data.candidate_count === 0) {
                lines.push('WebRTC 被禁用或阻断');
            }
            if (!lines.length) {
                lines.push('检测完成：' + (state || 'unknown'));
            }
            return lines.join('\n');
        },

        async runWebrtcCheck() {
            this.webrtcError = '';
            this.webrtcMessage = '';
            var httpIp = this.latestCheckedIp();
            if (!httpIp) {
                this.webrtcError = '请先检测节点';
                return;
            }
            this.webrtcRunning = true;
            this.webrtcMessage = '正在收集 ICE candidates...';
            try {
                var candidates = await gatherCandidates();
                var res = await fetch('/api/webrtc-report', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ candidates: candidates, http_ip: httpIp })
                });
                if (!res.ok) {
                    throw new Error('服务器返回 ' + res.status);
                }
                var data = await res.json();
                this.webrtcMessage = this.formatWebrtcResult(data);
            } catch (e) {
                this.webrtcMessage = '';
                this.webrtcError = (e && e.message) ? e.message : String(e);
            } finally {
                this.webrtcRunning = false;
            }
        },

        cycleSortByScore() {
            if (this.sortByScore === null) {
                this.sortByScore = 'desc';
            } else if (this.sortByScore === 'desc') {
                this.sortByScore = 'asc';
            } else {
                this.sortByScore = null;
            }
        },

        sortByScoreLabel() {
            if (this.sortByScore === 'desc') {
                return '综合分 ↓';
            }
            if (this.sortByScore === 'asc') {
                return '综合分 ↑';
            }
            return '按综合分排序';
        },

        sortedNodes() {
            var nodes = this.nodes || [];
            var mode = this.sortByScore;
            if (!mode) {
                return nodes;
            }
            var indexed = [];
            var i;
            for (i = 0; i < nodes.length; i++) {
                indexed.push({ node: nodes[i], idx: i });
            }
            indexed.sort(function (a, b) {
                var sa = a.node ? a.node.risk_score : null;
                var sb = b.node ? b.node.risk_score : null;
                var aValid = sa !== null && sa !== undefined && sa !== '';
                var bValid = sb !== null && sb !== undefined && sb !== '';
                if (aValid && !bValid) {
                    return -1;
                }
                if (!aValid && bValid) {
                    return 1;
                }
                if (!aValid && !bValid) {
                    return a.idx - b.idx;
                }
                var diff = Number(sa) - Number(sb);
                if (mode === 'desc') {
                    diff = -diff;
                }
                if (diff !== 0) {
                    return diff;
                }
                return a.idx - b.idx;
            });
            var out = [];
            for (i = 0; i < indexed.length; i++) {
                out.push(indexed[i].node);
            }
            return out;
        },

        riskScoreClass(level) {
            if (level === '低风险') {
                return 'risk-green';
            }
            if (level === '中风险') {
                return 'risk-yellow';
            }
            if (level === '高风险') {
                return 'risk-red';
            }
            return '';
        },

        formatRiskScore(node) {
            if (!node || node.risk_score === null || node.risk_score === undefined || node.risk_score === '') {
                return '—';
            }
            var level = node.risk_level || '';
            if (level && level !== '未知') {
                return node.risk_score + ' ' + level;
            }
            return String(node.risk_score);
        },

        getRiskMark(node) {
            if (!node) return { text: '—', cls: '' };
            if (node.dnsbl_blacklisted) {
                const zones = Array.isArray(node.dnsbl_hits) ? node.dnsbl_hits.join(', ') : '';
                return { text: `⛔ 黑名单: ${zones}`, cls: 'risk-black' };
            }
            if (node.ipqs_veto) {
                return { text: '🛑 高风控', cls: 'risk-red' };
            }
            return { text: '—', cls: '' };
        },

        // Risk color class based on percentage (Matches Python get_emoji logic)
        getRiskClass(risk) {
            if (!risk || risk === '❓' || risk === 'N/A') return '';
            const num = parseInt(risk);
            if (isNaN(num)) return '';

            if (num <= 10) return 'risk-white';
            if (num <= 30) return 'risk-green';
            if (num <= 50) return 'risk-yellow';
            if (num <= 70) return 'risk-orange';
            if (num <= 90) return 'risk-red';
            return 'risk-black';
        },

        // Shared users color class (Matches Python logic: <=10, <=100, <=1000, <=10000, >10000)
        // Latency from the Clash delay test (parallel path only)
        formatDelay(node) {
            const d = node && node.delay_ms;
            return (typeof d === 'number' && d > 0) ? `${d}ms` : '—';
        },

        delayClass(node) {
            const d = node && node.delay_ms;
            if (typeof d !== 'number' || d <= 0) return '';
            if (d < 150) return 'risk-green';
            if (d < 400) return 'shared-orange';
            return 'risk-red';
        },

        formatIPv6(node) {
            return node && node.ipv6 ? '✓ v6' : '—';
        },

        getSharedClass(shared) {
            if (!shared || shared === 'N/A' || shared === '❓') return '';

            // Extract numbers from string (e.g. "100-500" -> [100, 500])
            const nums = String(shared).match(/\d+/g);
            if (!nums || nums.length === 0) return '';

            // Use the upper bound (last number) logic
            let upper = parseInt(nums[nums.length - 1]);

            // If contains '+', increment to push to next category (e.g. 10000+ -> 10001 -> Black)
            if (String(shared).includes('+')) {
                upper += 1;
            }

            if (upper <= 10) return 'shared-green';
            if (upper <= 100) return 'shared-yellow';
            if (upper <= 1000) return 'shared-orange';
            if (upper <= 10000) return 'shared-red';
            return 'shared-black';
        },

        // Export
        async exportYaml() {
            if (this.selected.length === 0) {
                alert('请先选择要导出的节点');
                return;
            }

            try {
                const res = await fetch('/api/export', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ node_ids: this.selected })
                });

                const data = await res.json();
                this.exportedYaml = data.yaml;
                this.exportFilename = data.filename;
                this.exportUrl = data.url;
                this.subscribeUrl = data.subscribe_url || '';
                this.$refs.exportModal.showModal();

                // Initialize Export Editor
                this.$nextTick(() => {
                    const el = document.getElementById('export-editor');
                    if (!el) return;

                    // Clear and recreate to avoid stale content
                    el.innerHTML = '';
                    this.exportEditor = CodeMirror(el, {
                        mode: 'yaml',
                        theme: 'material-darker',
                        lineNumbers: true,
                        readOnly: true,
                        lineWrapping: true,
                        value: this.exportedYaml
                    });
                    setTimeout(() => this.exportEditor.refresh(), 50);
                });

            } catch (e) {
                alert(`导出失败: ${e.message}`);
            }
        },

        downloadYaml() {
            const blob = new Blob([this.exportedYaml], { type: 'application/x-yaml' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = this.exportFilename;
            a.click();
            URL.revokeObjectURL(url);
        },

        async copyYaml() {
            try {
                await navigator.clipboard.writeText(this.exportedYaml);
                alert('已复制到剪贴板');
            } catch (e) {
                alert('复制失败');
            }
        },

        absoluteSubscribeUrl() {
            if (!this.subscribeUrl) return '';
            return `${window.location.protocol}//${window.location.host}${this.subscribeUrl}`;
        },

        async copySubscribeUrl() {
            try {
                await navigator.clipboard.writeText(this.absoluteSubscribeUrl());
                alert('已复制订阅更新链接');
            } catch (e) {
                alert('复制失败');
            }
        },

        importToClash() {
            // Prefer the stable subscribe URL: it stays alive with the web
            // server, so Verge 更新 refreshes scores on the same profile.
            const path = this.subscribeUrl || this.exportUrl;
            if (!path) {
                alert('未找到导出链接');
                return;
            }
            const fullUrl = encodeURIComponent(`${window.location.protocol}//${window.location.host}${path}`);
            const name = encodeURIComponent(this.exportFilename.replace('.yaml', ''));
            // Schema: clash://install-config?url=xxx&name=xxx
            window.location.href = `clash://install-config?url=${fullUrl}&name=${name}`;
        }
    };
}
