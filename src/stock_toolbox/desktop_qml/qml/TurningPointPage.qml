pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."
import "components"

Item {
    id: page
    signal networkSettingsRequested()
    objectName: "turningPointPage"

    readonly property bool historyMode: {
        // qmllint disable unqualified
        return shellBridge.current_page === "turning_point.history"
        // qmllint enable unqualified
    }
    property string exportRunId: ""
    property bool missOverlayOpen: false
    property bool reportDialogOpen: false
    property string visibleRunId: ""
    // qmllint disable unqualified
    readonly property bool hasSelectedHistory:
        turningPointBridge.selected_run_id.length > 0
    readonly property string reportErrorText:
        turningPointBridge.report_error
    readonly property bool modalOverlayOpen:
        missOverlayOpen || turningPointBridge.requires_budget_confirmation
        || turningPointBridge.fallback_gate.pending
        || failureDetail.visible || reportDialogOpen
    // qmllint enable unqualified
    readonly property bool compactHeight: height < 720
    readonly property bool narrowResults: width < 900
    readonly property var stageNames: [
        "冻结股票池", "服务端指标", "计算信号", "风险标注", "保存"
    ]

    function handleOutcomeAction(action): void {
        if (action === "open_settings") {
            // qmllint disable unqualified
            shellBridge.open_settings()
            // qmllint enable unqualified
        } else if (action === "retry") {
            // qmllint disable unqualified
            turningPointBridge.start()
            // qmllint enable unqualified
        }
    }

    function watchlistLabel(): string {
        // qmllint disable unqualified
        const rows = turningPointBridge.watchlists
        const selected = turningPointBridge.selected_watchlist_id
        // qmllint enable unqualified
        for (let index = 0; index < rows.length; ++index) {
            if (rows[index].id === selected) {
                return rows[index].name + " · " + rows[index].memberCount + " 只"
            }
        }
        // qmllint disable unqualified
        const loading = turningPointBridge.support_loading
        // qmllint enable unqualified
        return loading
            ? "正在读取股票池…" : "选择股票池"
    }

    function missReasonText(periods): string {
        const parts = []
        for (let index = 0; index < periods.length; ++index) {
            parts.push(periods[index].intervalLabel + "："
                + periods[index].reasonLabel)
        }
        return parts.join("\n")
    }

    function ensureHistorySelection(): void {
        if (!page.historyMode) {
            return
        }
        // qmllint disable unqualified
        const rows = turningPointBridge.history
        const selected = turningPointBridge.selected_run_id
        // qmllint enable unqualified
        if (rows.length === 0) {
            return
        }
        const runId = selected.length > 0 ? selected : rows[0].runId
        page.exportRunId = runId
        // qmllint disable unqualified
        turningPointBridge.select_run(runId)
        // qmllint enable unqualified
    }

    onHistoryModeChanged: {
        if (page.historyMode) {
            page.ensureHistorySelection()
        } else {
            // qmllint disable unqualified
            turningPointBridge.prepare_new_run()
            // qmllint enable unqualified
        }
    }
    onVisibleChanged: {
        if (visible && !page.historyMode) {
            // qmllint disable unqualified
            turningPointBridge.prepare_new_run()
            // qmllint enable unqualified
        }
    }

    FileDialog {
        id: exportDialog
        fileMode: FileDialog.SaveFile
        nameFilters: ["拐点筛选表格 (*.csv)"]
        defaultSuffix: "csv"
        onAccepted: {
            // qmllint disable unqualified
            turningPointBridge.export_history(
                page.exportRunId, selectedFile.toString())
            // qmllint enable unqualified
        }
    }

    Component.onCompleted: {
        // qmllint disable unqualified
        if (!page.historyMode) {
            turningPointBridge.prepare_new_run()
        }
        turningPointBridge.load_support_data()
        if (!turningPointBridge.end_date) {
            turningPointBridge.refresh_latest_trading_day()
        }
        // qmllint enable unqualified
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 58

            Column {
                spacing: 5
                Text {
                    text: page.historyMode ? "拐点筛选历史" : "拐点筛选"
                    color: Theme.text
                    font.pixelSize: 25
                    font.weight: Font.Bold
                }
                Text {
                    // qmllint disable unqualified
                    text: page.historyMode
                        ? "每只证券聚合为一行，按命中周期和关注度安排复盘顺序。"
                        : (turningPointBridge.trade_side === "LEFT_CD"
                            ? "寻找 CCC 首次成立的 CD 底背离信号，不预测未来收益。"
                            : "寻找底背离后向上穿越均线的确认信号，不预测未来收益。")
                    // qmllint enable unqualified
                    color: Theme.secondaryText
                    font.pixelSize: 12
                }
            }
            Item { Layout.fillWidth: true }
            Text {
                visible: !page.historyMode
                text: "逐项容错 · 最多四路行情并发"
                color: Theme.secondaryText
                font.pixelSize: 11
            }
        }

        GlassPanel {
            // qmllint disable unqualified
            visible: !page.historyMode
                && !(page.compactHeight
                    && turningPointBridge.results_available)
            // qmllint enable unqualified
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 62 : 0
            Layout.minimumHeight: 0
            Layout.maximumHeight: visible ? 62 : 0

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                spacing: 12
                Text {
                    text: "怎么阅读"
                    color: Theme.accent
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: "先选择股票池、结束日期和一个或多个周期。结果只列出命中证券；"
                        + "左侧交易位置更早、噪音更高；右侧交易位置更晚、确认程度更高。"
                        + "短周期更灵敏但噪音更高，日线和周线更慢但可靠性更强。"
                        + "命中后才补充小市值风险标注；综合分用于安排复盘优先级，"
                        + "不预测未来。"
                    color: Theme.secondaryText
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }
            }
        }

        RowLayout {
            objectName: "turningRunSurface"
            visible: !page.historyMode
            Layout.fillWidth: true
            Layout.preferredHeight: 206
            Layout.maximumHeight: 206
            spacing: 12

            GlassPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 5

                    Text {
                        text: "股票池与日期"
                        color: Theme.text
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 5
                        Text {
                            text: "股票池"
                            color: Theme.secondaryText
                            font.pixelSize: 11
                        }
                        GlassField {
                            Layout.fillWidth: true
                            valueText: page.watchlistLabel()
                            // qmllint disable unqualified
                            model: turningPointBridge.watchlists
                            loading: turningPointBridge.support_loading
                            loaded: turningPointBridge.support_loaded
                            // qmllint enable unqualified
                            emptyText: "还没有股票池"
                            textRole: "name"
                            valueRole: "id"
                            // qmllint disable unqualified
                            onOpening: turningPointBridge.load_support_data()
                            // qmllint enable unqualified
                            onActivated: {
                                // qmllint disable unqualified
                                turningPointBridge.select_watchlist(currentValue)
                                // qmllint enable unqualified
                            }
                        }
                        Text {
                            text: "结束日期"
                            color: Theme.secondaryText
                            font.pixelSize: 11
                        }
                        DatePickerField {
                            Layout.fillWidth: true
                            // qmllint disable unqualified
                            dateValue: turningPointBridge.end_date
                            maximumDate: turningPointBridge
                                .maximum_historical_date
                            loading: turningPointBridge.calendar_loading
                            // qmllint enable unqualified
                            placeholderText: "YYYY-MM-DD"
                            onDateSelected: value => {
                                // qmllint disable unqualified
                                turningPointBridge.set_end_date(value)
                                // qmllint enable unqualified
                            }
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "休市日自动探测前后 4 个工作日；结果冻结实际交易日。"
                        color: Theme.faintText
                        font.pixelSize: 9
                        elide: Text.ElideRight
                    }
                }
            }

            GlassPanel {
                objectName: "turningStrategyPanel"
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 5
                    Text {
                        text: "策略与周期"
                        color: Theme.text
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 7
                        // qmllint disable unqualified
                        ChoiceChip {
                            objectName: "turningLeftChoice"
                            Layout.fillWidth: true
                            rightPadding: 34
                            text: "左侧 · CD"
                            Accessible.description: "交易侧：左侧 CD"
                            checked: turningPointBridge.trade_side === "LEFT_CD"
                            enabled: !turningPointBridge.running
                            onClicked: turningPointBridge
                                .set_trade_side("LEFT_CD")
                            InfoTip {
                                objectName: "turningLeftHelp"
                                anchors.right: parent.right
                                anchors.rightMargin: 9
                                anchors.verticalCenter: parent.verticalCenter
                                title: "左侧交易 · CD 如何命中"
                                preferredWidth: 390
                                lightSurface: true
                                tipText: "只看完整 K 线：30 分钟最近 65 根、1 小时 35 根、2 小时 20 根、4 小时 10 根、日线 20 根、周线 8 根。CCC 从未成立变为成立的首根 K 线即命中；后续 DIF 收缩只记为增强确认，不阻止命中。"
                            }
                        }
                        ChoiceChip {
                            objectName: "turningRightChoice"
                            Layout.fillWidth: true
                            rightPadding: 34
                            text: "右侧 · 均线确认"
                            Accessible.description: "交易侧：右侧均线确认"
                            checked: turningPointBridge.trade_side
                                === "RIGHT_CONFIRMED"
                            enabled: !turningPointBridge.running
                            onClicked: turningPointBridge
                                .set_trade_side("RIGHT_CONFIRMED")
                            InfoTip {
                                objectName: "turningRightHelp"
                                anchors.right: parent.right
                                anchors.rightMargin: 9
                                anchors.verticalCenter: parent.verticalCenter
                                title: "右侧交易 · 均线确认"
                                preferredWidth: 390
                                openLeft: true
                                lightSurface: true
                                tipText: "先出现同周期 CD，且信号 K 线 High EMA26 低于 High EMA89；随后最多 20 根完整 K 线内，收盘价从下向上站上 High EMA26 才命中。超过窗口仍未站上则不命中。"
                            }
                        }
                        // qmllint enable unqualified
                    }
                    Text {
                        Layout.fillWidth: true
                        // qmllint disable unqualified
                        text: turningPointBridge.trade_side === "LEFT_CD"
                            ? "CCC 首次成立即命中；DIF 后续收缩只记为增强确认。"
                            : "CD 当根处于弱势结构，随后 20 根内站上 High EMA26。"
                        // qmllint enable unqualified
                        color: Theme.secondaryText
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                    Text {
                        text: "K 线周期 · 至少保留一个"
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                    GridLayout {
                        objectName: "turningIntervalGrid"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 70
                        columns: 3
                        uniformCellWidths: true
                        columnSpacing: 6
                        rowSpacing: 6
                        Repeater {
                            // qmllint disable unqualified
                            model: turningPointBridge.intervals
                            // qmllint enable unqualified
                            ChoiceChip {
                                required property var modelData
                                Layout.fillWidth: true
                                text: modelData.label
                                checked: modelData.selected
                                // qmllint disable unqualified
                                enabled: !turningPointBridge.running
                                onToggled: {
                                    turningPointBridge.set_interval_selected(
                                        modelData.value, checked)
                                    // qmllint enable unqualified
                                }
                            }
                        }
                    }
                }
            }
        }

        GlassPanel {
            objectName: "turningRunConsole"
            visible: !page.historyMode
            Layout.fillWidth: true
            // The outcome content wraps at narrow widths.  Its height must
            // drive the container; fixed caps previously made the card and
            // stage strip paint over one another.
            Layout.preferredHeight: Math.max(112, outcomeCard.implicitHeight + 28)

            RowLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 12
                RunOutcomeCard {
                    id: outcomeCard
                    objectName: "turningOutcomeCard"
                    Layout.fillWidth: true
                    Layout.maximumWidth: 520
                    Layout.preferredHeight: implicitHeight
                    // qmllint disable unqualified
                    running: turningPointBridge.running
                    recoveryVisible: turningPointBridge.recovery_visible
                    recoveryTone: turningPointBridge.recovery_tone
                    recoveryMessage: turningPointBridge.recovery_message
                    retryCount: turningPointBridge.retry_count
                    waitSeconds: turningPointBridge.wait_seconds
                    activeConcurrency: turningPointBridge.active_concurrency
                    outcomeVisible: turningPointBridge.outcome_visible
                    outcomeTone: turningPointBridge.outcome_tone
                    outcomeTitle: turningPointBridge.outcome_title
                    outcomeSummary: turningPointBridge.outcome_summary
                    primaryAction: turningPointBridge.outcome_primary_action
                    primaryLabel: turningPointBridge.outcome_primary_label
                    failureCount: turningPointBridge.failure_count
                    runningReason: turningPointBridge.status_text
                    progress: turningPointBridge.progress
                    // qmllint enable unqualified
                    runningTitle: "计算进度"
                    onPrimaryActionRequested:
                        action => page.handleOutcomeAction(action)
                    onDetailsRequested: {
                        // qmllint disable unqualified
                        failureDetail.openWithSnapshot(turningPointBridge.failure_groups)
                        // qmllint enable unqualified
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    // qmllint disable unqualified
                    visible: !turningPointBridge.running
                        && !turningPointBridge.outcome_visible
                    // qmllint enable unqualified
                    spacing: 5
                    Item { Layout.fillHeight: true }
                    Text {
                        Layout.fillWidth: true
                        text: "等待开始"
                        color: Theme.text
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "先检查本机缓存与额度，再启动最多四路并发计算。"
                        color: Theme.secondaryText
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                    Item { Layout.fillHeight: true }
                }
                ColumnLayout {
                    Layout.minimumWidth: 170
                    Layout.preferredWidth: 170
                    Layout.maximumWidth: 170
                    Layout.fillHeight: true
                    // qmllint disable unqualified
                    visible: turningPointBridge.running
                        || turningPointBridge.outcome_visible
                    // qmllint enable unqualified
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        GlassMetric {
                            objectName: "turningMatchedMetric"
                            Layout.fillWidth: true
                            compact: true
                            label: "命中"
                            // qmllint disable unqualified
                            value: String(turningPointBridge.matched_count)
                            // qmllint enable unqualified
                        }
                        GlassMetric {
                            objectName: "turningFailureMetric"
                            Layout.fillWidth: true
                            compact: true
                            label: "失败"
                            // qmllint disable unqualified
                            value: String(turningPointBridge.failure_count)
                            // qmllint enable unqualified
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        // qmllint disable unqualified
                        text: turningPointBridge.trade_side_label
                        // qmllint enable unqualified
                        color: Theme.accent
                        font.pixelSize: 10
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
                ColumnLayout {
                    Layout.minimumWidth: 118
                    Layout.preferredWidth: 118
                    Layout.maximumWidth: 118
                    Layout.fillHeight: true
                    spacing: 8
                    Item { Layout.fillHeight: true }
                    GlassButton {
                        objectName: "turningCancelButton"
                        Layout.fillWidth: true
                        text: "取消计算"
                        // qmllint disable unqualified
                        visible: turningPointBridge.running
                        enabled: turningPointBridge.running
                        onClicked: turningPointBridge.cancel()
                        // qmllint enable unqualified
                    }
                    GlassButton {
                        objectName: "turningStartButton"
                        Layout.fillWidth: true
                        text: busy ? "计算中" : "开始计算"
                        primary: true
                        // qmllint disable unqualified
                        busy: turningPointBridge.budget_loading
                            || turningPointBridge.running
                        visible: !turningPointBridge.running
                            && (!turningPointBridge.outcome_visible
                                || !turningPointBridge.outcome_primary_action)
                        enabled: turningPointBridge.can_start
                        onClicked: turningPointBridge.start()
                        // qmllint enable unqualified
                    }
                    Item { Layout.fillHeight: true }
                }
            }
        }

        ResourceBudgetCard {
            objectName: "turningResourceBudget"
            // qmllint disable unqualified
            visible: !page.historyMode
                && turningPointBridge.budget_loading
            // qmllint enable unqualified
            Layout.fillWidth: true
            // qmllint disable unqualified
            loading: turningPointBridge.budget_loading
            memberCount: turningPointBridge.member_count
            dimensionCount: turningPointBridge.selected_interval_count
            totalTasks: turningPointBridge.estimated_total
            cacheHits: turningPointBridge.estimated_cache_hits
            coldRequests: turningPointBridge.estimated_cold_requests
            dataPath: turningPointBridge.data_path
            quotaNotice: turningPointBridge.quota_notice
            // qmllint enable unqualified
        }

        StageStrip {
            objectName: "turningStageStrip"
            // qmllint disable unqualified
            visible: !page.historyMode && turningPointBridge.running
            // qmllint enable unqualified
            Layout.fillWidth: true
            stages: page.stageNames
            // qmllint disable unqualified
            activeIndex: turningPointBridge.running
                ? turningPointBridge.active_stage : -1
            progress: turningPointBridge.progress
            // qmllint enable unqualified
        }

        Item {
            visible: !page.historyMode
            Layout.fillHeight: true
        }

        RowLayout {
            objectName: "turningHistorySurface"
            visible: page.historyMode
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            GlassPanel {
                visible: page.historyMode
                Layout.preferredWidth: 250
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 8
                    Text {
                        text: "最近十次"
                        color: Theme.text
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        ListView {
                            id: turningHistoryList
                            anchors.fill: parent
                            spacing: 7
                            clip: true
                            // qmllint disable unqualified
                            model: turningPointBridge.history
                            // qmllint enable unqualified
                            delegate: Rectangle {
                                id: historyRow
                                required property var modelData
                                width: ListView.view.width
                                height: 82
                                radius: 13
                                // qmllint disable unqualified
                                color: historyRow.modelData.runId
                                    === turningPointBridge.selected_run_id
                                    ? Theme.accentSoft : Theme.field
                                // qmllint enable unqualified
                                border.width: 1
                                // qmllint disable unqualified
                                border.color: historyRow.modelData.runId
                                    === turningPointBridge.selected_run_id
                                    ? Theme.accent : Theme.hairline
                                // qmllint enable unqualified
                                Column {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 4
                                    Text {
                                        text: (historyRow.modelData.pinned ? "● " : "")
                                            + historyRow.modelData.name
                                        color: Theme.text
                                        font.pixelSize: 11
                                        font.weight: Font.Medium
                                        width: historyRow.width - 24
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        text: "操作于 "
                                            + historyRow.modelData.completedAt
                                        color: Theme.secondaryText
                                        font.pixelSize: 9
                                    }
                                    Text {
                                        text: "命中 " + historyRow.modelData.matchedCount
                                            + " / " + historyRow.modelData.totalCount
                                            + " · " + historyRow.modelData.intervals.length
                                            + " 周期 · " + historyRow.modelData.provider
                                        color: Theme.faintText
                                        font.pixelSize: 9
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: {
                                        page.exportRunId = historyRow.modelData.runId
                                        // qmllint disable unqualified
                                        turningPointBridge.select_run(
                                            historyRow.modelData.runId)
                                        // qmllint enable unqualified
                                    }
                                }
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: turningHistoryList.count === 0
                            text: "暂无记录"
                            color: Theme.faintText
                            font.pixelSize: 11
                        }
                    }
                }
            }

            GlassPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 8

                    ColumnLayout {
                        objectName: "turningHistoryRecordContent"
                        visible: page.hasSelectedHistory
                        Layout.fillWidth: true
                        spacing: 7
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                // qmllint disable unqualified
                                text: "记录结果 · "
                                    + turningPointBridge.trade_side_label
                                // qmllint enable unqualified
                                color: Theme.text
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                // qmllint disable unqualified
                                visible: !turningPointBridge.ai_configured
                                // qmllint enable unqualified
                                text: "配置 AI 后可生成解读"
                                color: Theme.faintText
                                font.pixelSize: 10
                            }
                        }
                        Flow {
                            Layout.fillWidth: true
                            Layout.preferredHeight: childrenRect.height
                            spacing: 7
                            GlassButton {
                                text: {
                                    // qmllint disable unqualified
                                    return turningPointBridge.report_running
                                        ? "AI 解读中…"
                                        : (turningPointBridge.report_text.length > 0
                                            ? "查看 AI 解读" : "生成 AI 解读")
                                    // qmllint enable unqualified
                                }
                                // qmllint disable unqualified
                                enabled: turningPointBridge.ai_configured
                                    && turningPointBridge.matched_count > 0
                                    && !turningPointBridge.report_running
                                onClicked: {
                                    if (turningPointBridge.report_text.length > 0) {
                                        page.reportDialogOpen = true
                                    } else {
                                        turningPointBridge.generate_report()
                                    }
                                }
                                // qmllint enable unqualified
                            }
                            GlassButton {
                                // qmllint disable unqualified
                                text: turningPointBridge.selected_run_pinned
                                    ? "取消固定" : "固定"
                                enabled: turningPointBridge.selected_run_id.length > 0
                                // qmllint enable unqualified
                                onClicked: {
                                    // qmllint disable unqualified
                                    turningPointBridge.set_pinned(
                                        turningPointBridge.selected_run_id,
                                        !turningPointBridge.selected_run_pinned)
                                    // qmllint enable unqualified
                                }
                            }
                            GlassButton {
                                text: "完整导出"
                                // qmllint disable unqualified
                                enabled: turningPointBridge.selected_run_id.length > 0
                                // qmllint enable unqualified
                                onClicked: {
                                    // qmllint disable unqualified
                                    exportDialog.currentFile = turningPointBridge.export_default_url
                                    // qmllint enable unqualified
                                    exportDialog.open()
                                }
                            }
                            GlassButton {
                                // qmllint disable unqualified
                                text: "查看未命中 · "
                                    + turningPointBridge.unmatched_count
                                enabled: turningPointBridge.unmatched_count > 0
                                visible: turningPointBridge.matched_count > 0
                                // qmllint enable unqualified
                                onClicked: page.missOverlayOpen = true
                            }
                        }
                    }

                    Flow {
                        objectName: "turningHistoryResultFilters"
                        // qmllint disable unqualified
                        visible: turningPointBridge.results_available
                        // qmllint enable unqualified
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(32, childrenRect.height)
                        spacing: 7
                        Repeater {
                            // qmllint disable unqualified
                            model: turningPointBridge.result_filters
                            // qmllint enable unqualified
                            ChoiceChip {
                                required property var modelData
                                text: modelData.label + " " + modelData.count
                                checked: modelData.selected
                                onClicked: {
                                    // qmllint disable unqualified
                                    turningPointBridge.select_result_interval(
                                        modelData.value)
                                    // qmllint enable unqualified
                                }
                            }
                        }
                    }

                    ListView {
                        objectName: "turningInlineUnmatchedList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 7
                        // qmllint disable unqualified
                        visible: page.historyMode
                            && turningPointBridge.matched_count === 0
                            && turningPointBridge.unmatched_count > 0
                        model: visible ? turningPointBridge.unmatched_results : []
                        // qmllint enable unqualified
                        delegate: Rectangle {
                            id: inlineMissRow
                            required property var modelData
                            width: ListView.view.width
                            height: Math.max(74, inlineMissCopy.implicitHeight + 34)
                            radius: 12
                            color: Theme.field
                            border.width: 1
                            border.color: Theme.hairline
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 14
                                Column {
                                    Layout.preferredWidth: 150
                                    spacing: 3
                                    Text {
                                        width: 150
                                        text: inlineMissRow.modelData.symbol
                                            + (inlineMissRow.modelData.companyName
                                                ? " · " + inlineMissRow.modelData.companyName
                                                : "")
                                        color: Theme.text
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        width: 150
                                        text: inlineMissRow.modelData.classificationName || "未分类"
                                        color: Theme.secondaryText
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }
                                }
                                Text {
                                    id: inlineMissCopy
                                    Layout.fillWidth: true
                                    text: page.missReasonText(
                                        inlineMissRow.modelData.periodResults)
                                    color: Theme.secondaryText
                                    font.pixelSize: 10
                                    lineHeight: 1.25
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                    }

                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 6
                        // qmllint disable unqualified
                        visible: turningPointBridge.matched_count > 0
                        model: turningPointBridge.results
                        // qmllint enable unqualified
                        delegate: Rectangle {
                            id: resultRow
                            required property var modelData
                            width: ListView.view.width
                            height: Math.max(76, resultRowContent.implicitHeight + 20)
                            radius: 12
                            color: Theme.field
                            border.width: 1
                            border.color: Theme.hairline

                            RowLayout {
                                id: resultRowContent
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                anchors.topMargin: 10
                                anchors.bottomMargin: 10
                                spacing: 10
                                Column {
                                    Layout.preferredWidth: 128
                                    spacing: 3
                                    Text {
                                        text: resultRow.modelData.symbol
                                            + (resultRow.modelData.companyName
                                                ? " · " + resultRow.modelData.companyName
                                                : "")
                                        color: Theme.text
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                        width: 128
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        text: resultRow.modelData.classificationName
                                        color: Theme.secondaryText
                                        font.pixelSize: 9
                                        width: 128
                                        elide: Text.ElideRight
                                    }
                                }
                                Column {
                                    Layout.preferredWidth: 142
                                    spacing: 3
                                    Flow {
                                        width: 142
                                        height: Math.max(22, childrenRect.height)
                                        spacing: 4
                                        // qmllint disable unqualified
                                        visible: turningPointBridge.result_view
                                            === "attention"
                                        // qmllint enable unqualified
                                        Repeater {
                                            model: resultRow.modelData
                                                .matchedPeriodChips
                                            Rectangle {
                                                id: periodChip
                                                required property var modelData
                                                width: periodChipText
                                                    .implicitWidth + 14
                                                height: 20
                                                radius: 8
                                                color: Theme.accentSoft
                                                border.width: 1
                                                border.color: Theme.accent
                                                Text {
                                                    id: periodChipText
                                                    anchors.centerIn: parent
                                                    text: periodChip.modelData.label
                                                    color: Theme.accent
                                                    font.pixelSize: 8
                                                    font.weight: Font.DemiBold
                                                }
                                                InfoTip {
                                                    anchors.fill: parent
                                                    showIndicator: false
                                                    lightSurface: true
                                                    openAbove: true
                                                    title: periodChip.modelData.label
                                                    tipText: periodChip.modelData.tip
                                                }
                                            }
                                        }
                                    }
                                    Text {
                                        // qmllint disable unqualified
                                        visible: turningPointBridge.result_view
                                            !== "attention"
                                        text: resultRow.modelData.selectedPeriod
                                            ? "CD " + resultRow.modelData
                                                .selectedPeriod.signalAt
                                            : ""
                                        // qmllint enable unqualified
                                        color: Theme.accent
                                        font.pixelSize: 10
                                        width: 142
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        // qmllint disable unqualified
                                        visible: turningPointBridge.result_view
                                            !== "attention"
                                        text: turningPointBridge.result_view
                                            === "attention" ? "" : (resultRow.modelData
                                                .selectedPeriod.crossedAt
                                                ? "确认 " + resultRow.modelData.selectedPeriod.crossedAt
                                                : (resultRow.modelData
                                                    .selectedPeriod.enhancedAt
                                                    ? "增强确认 " + resultRow.modelData.selectedPeriod.enhancedAt
                                                    : "左侧 CD 信号"))
                                        // qmllint enable unqualified
                                        color: Theme.secondaryText
                                        font.pixelSize: 9
                                        width: 142
                                        elide: Text.ElideRight
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    visible: !page.narrowResults
                                    spacing: 4
                                    Text {
                                        Layout.fillWidth: true
                                        // qmllint disable unqualified
                                        text: turningPointBridge.result_view
                                            === "attention"
                                            ? resultRow.modelData.conclusion
                                            : resultRow.modelData
                                                .selectedPeriod.signalLabel
                                                + (resultRow.modelData
                                                    .selectedPeriod.qualityScore
                                                    === null ? "" : " · 质量 "
                                                    + resultRow.modelData
                                                        .selectedPeriod.qualityScore)
                                        // qmllint enable unqualified
                                        color: Theme.secondaryText
                                        font.pixelSize: 9
                                        wrapMode: Text.Wrap
                                        maximumLineCount: 2
                                        elide: Text.ElideRight
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: visible ? 21 : 0
                                        visible: resultRow.modelData
                                            .riskLabels.length > 0
                                        spacing: 5
                                        Repeater {
                                            model: resultRow.modelData.riskLabels
                                            Rectangle {
                                                id: riskChip
                                                required property string modelData
                                                width: riskText.implicitWidth + 14
                                                height: 20
                                                radius: 8
                                                color: (
                                                    riskChip.modelData.indexOf("未知") >= 0
                                                    || riskChip.modelData.indexOf("不足") >= 0
                                                ) ? Theme.field : Theme.warningSoft
                                                border.width: 1
                                                border.color: (
                                                    riskChip.modelData.indexOf("未知") >= 0
                                                    || riskChip.modelData.indexOf("不足") >= 0
                                                ) ? Theme.hairline : Theme.warning
                                                Text {
                                                    id: riskText
                                                    anchors.centerIn: parent
                                                    text: riskChip.modelData
                                                    color: (
                                                        riskChip.modelData.indexOf("未知") >= 0
                                                        || riskChip.modelData.indexOf("不足") >= 0
                                                    ) ? Theme.secondaryText
                                                        : Theme.warning
                                                    font.pixelSize: 8
                                                    font.weight: Font.Medium
                                                }
                                            }
                                        }
                                    }
                                }
                                Column {
                                    Layout.preferredWidth: 72
                                    // qmllint disable unqualified
                                    visible: turningPointBridge.result_view
                                        === "attention"
                                    // qmllint enable unqualified
                                    spacing: 3
                                    Text {
                                        text: resultRow.modelData.attentionScore
                                        color: Theme.text
                                        font.pixelSize: 18
                                        font.weight: Font.Bold
                                        horizontalAlignment: Text.AlignRight
                                        width: 72
                                    }
                                    Text {
                                        text: resultRow.modelData.attentionLevel
                                        color: Theme.accent
                                        font.pixelSize: 9
                                        horizontalAlignment: Text.AlignRight
                                        width: 72
                                    }
                                }
                            }
                        }
                    }

                    Item {
                        objectName: "turningHistoryEmptyState"
                        visible: !page.hasSelectedHistory
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        Column {
                            anchors.centerIn: parent
                            spacing: 7

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: "暂无拐点筛选记录"
                                color: Theme.text
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: "完成一次拐点筛选后，结果会显示在这里。"
                                color: Theme.faintText
                                font.pixelSize: 11
                            }
                        }
                    }
                    Text {
                        // qmllint disable unqualified
                        visible: page.hasSelectedHistory
                            && turningPointBridge.results.length === 0
                        // qmllint enable unqualified
                        Layout.alignment: Qt.AlignHCenter
                        // qmllint disable unqualified
                        text: page.historyMode
                            ? turningPointBridge.result_empty_text
                            : "运行完成后，仅命中的证券会出现在这里"
                        // qmllint enable unqualified
                        color: Theme.faintText
                        font.pixelSize: 11
                    }
                }
            }
        }

    }

    BudgetConfirmOverlay {
        // qmllint disable unqualified
        visible: turningPointBridge.requires_budget_confirmation
        memberCount: turningPointBridge.member_count
        dimensionCount: turningPointBridge.selected_interval_count
        totalTasks: turningPointBridge.estimated_total
        cacheHits: turningPointBridge.estimated_cache_hits
        coldRequests: turningPointBridge.estimated_cold_requests
        dataPath: turningPointBridge.data_path
        quotaNotice: turningPointBridge.quota_notice
        quotaRemaining: turningPointBridge.quota_remaining
        quotaNewSymbols: turningPointBridge.quota_new_symbols
        quotaShortfall: turningPointBridge.quota_shortfall
        futuSerialNotice: turningPointBridge.futu_serial_notice
        onConfirmRequested:
            turningPointBridge.confirm_budget_and_start()
        onYahooRequested:
            turningPointBridge.use_yahoo_for_budget_and_start()
        onDismissRequested:
            turningPointBridge.dismiss_budget_confirmation()
        // qmllint enable unqualified
    }

    FallbackConfirmOverlay {
        // qmllint disable unqualified
        gate: turningPointBridge.fallback_gate
        // qmllint enable unqualified
        onSettingsRequested: page.networkSettingsRequested()
    }

    FailureDetailOverlay {
        id: failureDetail
        objectName: "turningFailureDetailOverlay"
        anchors.fill: parent
    }

    RsAIReportOverlay {
        id: reportDialog
        anchors.fill: parent
        visible: page.reportDialogOpen
        // qmllint disable unqualified
        reportText: turningPointBridge.report_text
        errorText: page.reportErrorText
        running: turningPointBridge.report_running
        // qmllint enable unqualified
        titleText: "AI 拐点解读"
        subtitleText: "综合当前历史记录内所有命中证券与全部所选周期"
        footerText: "AI 只解释本次冻结结果，不会修改 CD 信号或关注分。"
        onCloseRequested: page.reportDialogOpen = false
        onRegenerateRequested: {
            // qmllint disable unqualified
            turningPointBridge.generate_report()
            // qmllint enable unqualified
        }
    }

    Connections {
        // qmllint disable unqualified
        target: turningPointBridge
        // qmllint enable unqualified
        function onChanged(): void {
            if (!page.historyMode) {
                return
            }
            // qmllint disable unqualified
            const rows = turningPointBridge.history
            const selected = turningPointBridge.selected_run_id
            // qmllint enable unqualified
            if (selected.length > 0) {
                page.exportRunId = selected
                if (page.visibleRunId !== selected) {
                    page.missOverlayOpen = false
                    page.visibleRunId = selected
                }
            } else if (rows.length > 0) {
                page.exportRunId = rows[0].runId
                // qmllint disable unqualified
                turningPointBridge.select_run(page.exportRunId)
                // qmllint enable unqualified
            }
        }
        function onReport_finished(): void {
            // qmllint disable unqualified
            if (turningPointBridge.report_text.length > 0
                    || page.reportErrorText.length > 0) {
                page.reportDialogOpen = true
            }
            // qmllint enable unqualified
        }
        function onFinished(result): void {
            // A completed run owns one frozen history record.  Keep the run
            // page focused on execution and reveal the result in its record.
            // qmllint disable unqualified
            if (!page.historyMode
                    && (turningPointBridge.last_status === "READY"
                        || turningPointBridge.last_status === "PARTIAL")
                    && turningPointBridge.selected_run_id.length > 0) {
                shellBridge.navigate("turning_point.history")
            }
            // qmllint enable unqualified
        }
    }

    Popup {
        id: missOverlay
        anchors.centerIn: Overlay.overlay
        width: Math.min(780, page.width - 96)
        // qmllint disable unqualified
        height: Math.min(
            520,
            Math.max(
                320,
                126 + Math.ceil(
                    turningPointBridge.unmatched_count / 2) * 112))
        // qmllint enable unqualified
        modal: true
        focus: true
        visible: page.missOverlayOpen
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: page.missOverlayOpen = false

        background: Rectangle {
            radius: 22
            color: Theme.dark ? "#FF2A2E35" : "#FFFFFFFF"
            border.width: 1
            border.color: Theme.hairline
        }

        contentItem: ColumnLayout {
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "未命中说明"
                    color: Theme.text
                    font.pixelSize: 18
                    font.weight: Font.Bold
                }
                Item { Layout.fillWidth: true }
                GlassButton {
                    text: "关闭"
                    onClicked: missOverlay.close()
                }
            }
            Text {
                Layout.fillWidth: true
                text: "按证券和已选周期说明为什么没有进入命中列表。"
                color: Theme.secondaryText
                font.pixelSize: 11
            }
            GridView {
                id: missGrid
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                cellWidth: width / 2
                cellHeight: 112
                // qmllint disable unqualified
                model: turningPointBridge.unmatched_results
                // qmllint enable unqualified
                delegate: Rectangle {
                    id: missRow
                    required property var modelData
                    width: missGrid.cellWidth - 8
                    height: 102
                    radius: 13
                    color: Theme.dark ? Theme.field : "#F6F7F9"
                    border.width: 1
                    border.color: Theme.dark ? Theme.hairline : "#E7E9EE"
                    Column {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 6
                        Text {
                            text: missRow.modelData.symbol
                                + (missRow.modelData.companyName
                                    ? " · " + missRow.modelData.companyName : "")
                            color: Theme.text
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                        }
                        Text {
                            width: parent.width
                            text: page.missReasonText(
                                missRow.modelData.periodResults)
                            color: Theme.secondaryText
                            font.pixelSize: 11
                            lineHeight: 1.2
                            wrapMode: Text.Wrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
