pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "."
import "components"

Item {
    id: page
    signal networkSettingsRequested()
    objectName: "rsRunPage"

    readonly property var stageNames: [
        "预检", "获取收盘结果", "数据校验", "个股 RS", "分类聚合", "保存结果"
    ]
    readonly property bool compactHeight: height < 720
    property bool compactConfigExpanded: false
    // qmllint disable unqualified
    readonly property bool modalOverlayOpen:
        rsRunBridge.requires_budget_confirmation
        || rsRunBridge.fallback_gate.pending
        || failureDetail.visible
    readonly property bool showLiveStatus: rsRunBridge.running
        || rsRunBridge.recovery_visible
        || rsRunBridge.outcome_visible
    // qmllint enable unqualified
    readonly property bool compactLiveFocus: compactHeight
        && showLiveStatus && !compactConfigExpanded

    function handleOutcomeAction(action): void {
        if (action === "open_settings") {
            // qmllint disable unqualified
            shellBridge.open_settings()
            // qmllint enable unqualified
        } else if (action === "retry") {
            // qmllint disable unqualified
            rsRunBridge.start()
            // qmllint enable unqualified
        }
    }

    function openFailureDetails(): void {
        // qmllint disable unqualified
        failureDetail.openWithSnapshot(rsRunBridge.failure_groups)
        // qmllint enable unqualified
    }

    Component.onCompleted: {
        // qmllint disable unqualified
        if (!rsRunBridge.end_date) {
            rsRunBridge.refresh_latest_trading_day()
        }
        // qmllint enable unqualified
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 96

            ColumnLayout {
                anchors.fill: parent
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 30

                    Text {
                        text: "RS 强度"
                        color: Theme.text
                        font.pixelSize: 25
                        font.weight: Font.Bold
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        // qmllint disable unqualified
                        text: rsRunBridge.provider_status
                        // qmllint enable unqualified
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                }

                Rectangle {
                    objectName: "rsReadingGuide"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 54
                    radius: 15
                    color: Theme.accentSoft
                    border.width: 1
                    border.color: Theme.hairline

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 11

                        Text {
                            text: "怎么阅读"
                            color: Theme.accent
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                        }
                        Rectangle {
                            Layout.preferredWidth: 1
                            Layout.preferredHeight: 25
                            color: Theme.hairline
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "先选择股票池、基准和周期。RS > 0 表示跑赢基准，"
                                + "RS < 0 表示跑输；分类综合同时观察中位 RS 与"
                                + "强势成员占比，周期分歧表示不同时间尺度方向不一致。"
                                + "用于横向比较和复盘，不预测未来。"
                            color: Theme.secondaryText
                            font.pixelSize: 10
                            lineHeight: 1.25
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }

        RowLayout {
            visible: !page.showLiveStatus && !page.compactHeight
            Layout.fillWidth: true
            Layout.preferredHeight: 84
            spacing: 12

            GlassMetric {
                Layout.fillWidth: true
                label: "股票池"
                // qmllint disable unqualified
                value: rsRunBridge.watchlist_name + " · " + rsRunBridge.member_count
                // qmllint enable unqualified
            }
            GlassMetric {
                Layout.fillWidth: true
                label: "分析周期"
                // qmllint disable unqualified
                value: rsRunBridge.range_count + " 个"
                // qmllint enable unqualified
            }
            GlassMetric {
                Layout.fillWidth: true
                label: "比较基准"
                // qmllint disable unqualified
                value: rsRunBridge.benchmark.split(".")[0]
                // qmllint enable unqualified
            }
        }

        GlassPanel {
            id: configPanel
            objectName: "runConfigPanel"
            Layout.fillWidth: true
            // qmllint disable unqualified
            Layout.preferredHeight: page.compactHeight
                ? Math.max(360, page.height - 108)
                : (rsRunBridge.custom_enabled ? 536 : 482)
                    + (page.showLiveStatus ? 78 : 0)
            // qmllint enable unqualified

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 11

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 26

                    Text {
                        text: "运行配置"
                        color: Theme.text
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }

                    Item { Layout.fillWidth: true }

                    Rectangle {
                        implicitWidth: passedLabel.implicitWidth + 20
                        implicitHeight: 26
                        radius: 13
                        color: Theme.successSoft

                        Text {
                            id: passedLabel
                            anchors.centerIn: parent
                            // qmllint disable unqualified
                            text: rsRunBridge.preflight_ready ? "已通过预检" : "等待预检"
                            // qmllint enable unqualified
                            color: Theme.success
                            font.pixelSize: 11
                        }
                    }
                }

                GridLayout {
                    visible: !page.compactLiveFocus
                    Layout.fillWidth: true
                    columns: 2
                    uniformCellWidths: true
                    columnSpacing: 18
                    rowSpacing: 9

                    Text {
                        text: "计算股票池"
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                    Text {
                        text: "独立基准"
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }

                    GlassField {
                        id: watchlistField
                        objectName: "rsWatchlistField"
                        Layout.fillWidth: true
                        // qmllint disable unqualified
                        valueText: rsRunBridge.watchlist_name
                        model: rsRunBridge.watchlists
                        loading: rsRunBridge.watchlists_loading
                        loaded: rsRunBridge.watchlists_loaded
                        // qmllint enable unqualified
                        emptyText: "还没有股票池，请先到全局数据创建"
                        textRole: "name"
                        valueRole: "id"
                        // qmllint disable unqualified
                        enabled: !rsRunBridge.running
                        // qmllint enable unqualified
                        onOpening: {
                            // qmllint disable unqualified
                            rsRunBridge.load_watchlists()
                            // qmllint enable unqualified
                        }
                        onActivated: {
                            // qmllint disable unqualified
                            rsRunBridge.select_watchlist(currentValue)
                            // qmllint enable unqualified
                        }
                    }
                    GlassField {
                        Layout.fillWidth: true
                        // qmllint disable unqualified
                        valueText: rsRunBridge.benchmark_label
                        // qmllint enable unqualified
                        model: [
                            {"id": "SPY.US", "name": "SPY · S&P 500"},
                            {"id": "QQQ.US", "name": "QQQ · Nasdaq 100"}
                        ]
                        textRole: "name"
                        valueRole: "id"
                        // qmllint disable unqualified
                        enabled: !rsRunBridge.running
                        // qmllint enable unqualified
                        onActivated: {
                            // qmllint disable unqualified
                            rsRunBridge.set_benchmark(currentValue)
                            // qmllint enable unqualified
                        }
                    }

                    Text {
                        text: "结束日期"
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                    Text {
                        text: "数据口径"
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }

                    DatePickerField {
                        objectName: "rsEndDatePicker"
                        Layout.fillWidth: true
                        // qmllint disable unqualified
                        dateValue: rsRunBridge.end_date
                        maximumDate: rsRunBridge.maximum_historical_date
                        loading: rsRunBridge.calendar_loading
                        enabled: !rsRunBridge.running
                        // qmllint enable unqualified
                        placeholderText: "选择结束日期"
                        onDateSelected: function(value) {
                            // qmllint disable unqualified
                            rsRunBridge.set_end_date(value)
                            // qmllint enable unqualified
                        }
                    }
                    GlassField {
                        Layout.fillWidth: true
                        valueText: "最新完整交易日"
                        trailingText: "只读"
                        enabled: false
                    }
                }

                Text {
                    visible: !page.compactLiveFocus
                    Layout.fillWidth: true
                    text: "休市日自动探测前后 4 个工作日；结果保留所选与实际交易日。"
                    color: Theme.faintText
                    font.pixelSize: 9
                    elide: Text.ElideRight
                }

                Flow {
                    visible: !page.compactLiveFocus
                    Layout.fillWidth: true
                    Layout.preferredHeight: childrenRect.height
                    spacing: 9

                    Repeater {
                        // qmllint disable unqualified
                        model: rsRunBridge.ranges
                        // qmllint enable unqualified

                        ChoiceChip {
                            required property var modelData
                            text: modelData.label
                            checked: modelData.selected
                            // qmllint disable unqualified
                            enabled: !rsRunBridge.running
                            // qmllint enable unqualified
                            onToggled: {
                                // qmllint disable unqualified
                                rsRunBridge.toggle_range(modelData.key, checked)
                                // qmllint enable unqualified
                            }
                        }
                    }

                    ChoiceChip {
                        text: "自定义区间"
                        // qmllint disable unqualified
                        checked: rsRunBridge.custom_enabled
                        enabled: !rsRunBridge.running
                        // qmllint enable unqualified
                        onToggled: {
                            // qmllint disable unqualified
                            rsRunBridge.set_custom_enabled(checked)
                            // qmllint enable unqualified
                        }
                    }
                }

                RowLayout {
                    // qmllint disable unqualified
                    visible: rsRunBridge.custom_enabled
                        && !page.compactLiveFocus
                    // qmllint enable unqualified
                    Layout.fillWidth: true
                    Layout.preferredHeight: 50
                    spacing: 10

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text {
                            text: "自定义开始"
                            color: Theme.secondaryText
                            font.pixelSize: 10
                        }
                        DatePickerField {
                            objectName: "rsCustomStartPicker"
                            Layout.fillWidth: true
                            openAbove: true
                            // qmllint disable unqualified
                            dateValue: rsRunBridge.custom_start
                            maximumDate: rsRunBridge.maximum_historical_date
                            enabled: !rsRunBridge.running
                            // qmllint enable unqualified
                            onDateSelected: function(value) {
                                // qmllint disable unqualified
                                rsRunBridge.set_custom_dates(
                                    value, rsRunBridge.custom_end)
                                // qmllint enable unqualified
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text {
                            text: "自定义结束"
                            color: Theme.secondaryText
                            font.pixelSize: 10
                        }
                        DatePickerField {
                            objectName: "rsCustomEndPicker"
                            Layout.fillWidth: true
                            openAbove: true
                            // qmllint disable unqualified
                            dateValue: rsRunBridge.custom_end
                            maximumDate: rsRunBridge.maximum_historical_date
                            enabled: !rsRunBridge.running
                            // qmllint enable unqualified
                            onDateSelected: function(value) {
                                // qmllint disable unqualified
                                rsRunBridge.set_custom_dates(
                                    rsRunBridge.custom_start, value)
                                // qmllint enable unqualified
                            }
                        }
                    }
                }

                ResourceBudgetCard {
                    objectName: "rsResourceBudget"
                    visible: !page.compactLiveFocus
                    Layout.fillWidth: true
                    // qmllint disable unqualified
                    loading: rsRunBridge.budget_loading
                    memberCount: rsRunBridge.member_count
                    dimensionCount: rsRunBridge.range_count
                    totalTasks: rsRunBridge.estimated_total
                    cacheHits: rsRunBridge.estimated_cache_hits
                    coldRequests: rsRunBridge.estimated_cold_requests
                    dataPath: rsRunBridge.data_path
                    quotaNotice: rsRunBridge.quota_notice
                    // qmllint enable unqualified
                    dimensionLabel: "区间"
                }

                Rectangle {
                    objectName: "preflightBar"
                    visible: !page.showLiveStatus
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40
                    radius: 13
                    color: Theme.field
                    border.width: 1
                    border.color: Theme.hairline

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        // qmllint disable unqualified
                        text: rsRunBridge.preflight_text
                        // qmllint enable unqualified
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        text: "检查详情 ›"
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                }

                RunOutcomeCard {
                    id: liveStatusCard
                    objectName: "rsRunOutcomeCard"
                    Layout.fillWidth: true
                    Layout.preferredHeight: implicitHeight
                    // qmllint disable unqualified
                    running: rsRunBridge.running
                    recoveryVisible: rsRunBridge.recovery_visible
                    recoveryTone: rsRunBridge.recovery_tone
                    recoveryMessage: rsRunBridge.recovery_message
                    retryCount: rsRunBridge.retry_count
                    waitSeconds: rsRunBridge.wait_seconds
                    activeConcurrency: rsRunBridge.active_concurrency
                    outcomeVisible: rsRunBridge.outcome_visible
                    outcomeTone: rsRunBridge.outcome_tone
                    outcomeTitle: rsRunBridge.outcome_title
                    outcomeSummary: rsRunBridge.outcome_summary
                    primaryAction: rsRunBridge.outcome_primary_action
                    primaryLabel: rsRunBridge.outcome_primary_label
                    failureCount: rsRunBridge.failed_count
                    runningTitle: rsRunBridge.stage_label
                    runningReason: rsRunBridge.stage_detail
                    progress: rsRunBridge.progress
                    // qmllint enable unqualified
                    onPrimaryActionRequested:
                        action => page.handleOutcomeAction(action)
                    onDetailsRequested: page.openFailureDetails()
                }

                StageStrip {
                    objectName: "runStageStrip"
                    Layout.fillWidth: true
                    stages: page.stageNames
                    // qmllint disable unqualified
                    activeIndex: (rsRunBridge.running
                        || rsRunBridge.terminal_visible)
                        ? rsRunBridge.active_stage : -1
                    progress: rsRunBridge.progress
                    // qmllint enable unqualified
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40
                    Item { Layout.fillWidth: true }

                    GlassButton {
                        // qmllint disable unqualified
                        visible: page.compactLiveFocus
                            && !rsRunBridge.running
                        // qmllint enable unqualified
                        text: "调整配置"
                        onClicked: page.compactConfigExpanded = true
                    }
                    GlassButton {
                        objectName: "cancelRunButton"
                        text: "取消"
                        // qmllint disable unqualified
                        visible: rsRunBridge.running
                        enabled: rsRunBridge.cancel_available
                        onClicked: rsRunBridge.cancel()
                        // qmllint enable unqualified
                    }
                    GlassButton {
                        objectName: "startRunButton"
                        // qmllint disable unqualified
                        text: rsRunBridge.outcome_visible ? "重新运行" : "开始运行"
                        // qmllint enable unqualified
                        primary: true
                        // qmllint disable unqualified
                        visible: !rsRunBridge.outcome_visible
                            || rsRunBridge.outcome_primary_action !== "retry"
                        enabled: rsRunBridge.can_start
                        onClicked: rsRunBridge.start()
                        // qmllint enable unqualified
                        Accessible.name: "开始 RS 强度计算"
                    }
                }

                Item { Layout.fillHeight: true }
            }
        }

        Item { Layout.fillHeight: true }
    }

    BudgetConfirmOverlay {
        // qmllint disable unqualified
        visible: rsRunBridge.requires_budget_confirmation
        memberCount: rsRunBridge.member_count
        dimensionCount: rsRunBridge.range_count
        totalTasks: rsRunBridge.estimated_total
        cacheHits: rsRunBridge.estimated_cache_hits
        coldRequests: rsRunBridge.estimated_cold_requests
        dataPath: rsRunBridge.data_path
        quotaNotice: rsRunBridge.quota_notice
        quotaRemaining: rsRunBridge.quota_remaining
        quotaNewSymbols: rsRunBridge.quota_new_symbols
        quotaShortfall: rsRunBridge.quota_shortfall
        futuSerialNotice: rsRunBridge.futu_serial_notice
        onConfirmRequested: rsRunBridge.confirm_budget_and_start()
        onYahooRequested: rsRunBridge.use_yahoo_for_budget_and_start()
        onDismissRequested: rsRunBridge.dismiss_budget_confirmation()
        // qmllint enable unqualified
        dimensionLabel: "区间"
    }

    FallbackConfirmOverlay {
        // qmllint disable unqualified
        gate: rsRunBridge.fallback_gate
        // qmllint enable unqualified
        onSettingsRequested: page.networkSettingsRequested()
    }

    FailureDetailOverlay {
        id: failureDetail
        objectName: "rsFailureDetailOverlay"
        anchors.fill: parent
    }

    Connections {
        // qmllint disable unqualified
        target: rsRunBridge
        // qmllint enable unqualified
        function onChanged(): void {
            // qmllint disable unqualified
            if (rsRunBridge.running) {
                // qmllint enable unqualified
                page.compactConfigExpanded = false
            }
        }
    }
}
