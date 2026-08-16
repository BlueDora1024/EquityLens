pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "."
import "components"

Item {
    id: view
    signal networkSettingsRequested()
    // qmllint disable unqualified
    readonly property bool modalOverlayOpen:
        extremeDeviationBridge.requires_budget_confirmation
        || extremeDeviationBridge.fallback_gate.pending
        || failureDetail.visible
    // qmllint enable unqualified

    readonly property var stageNames: [
        "冻结证券", "检查缓存", "读取原始 K 线", "校验样本", "本地公式", "保存"
    ]
    readonly property bool preparing:
        // qmllint disable unqualified
        extremeDeviationBridge.securities_loading
        || extremeDeviationBridge.calendar_loading
        // qmllint enable unqualified
    property bool compactConfigExpanded: false
    readonly property bool compactHeight: height < 620
    // qmllint disable unqualified
    readonly property bool showLiveStatus: extremeDeviationBridge.running
        || extremeDeviationBridge.recovery_visible
        || extremeDeviationBridge.outcome_visible
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
            extremeDeviationBridge.start()
            // qmllint enable unqualified
        }
    }

    function displaySymbol(value): string {
        return String(value).replace(/\.US$/, "")
    }

    function securityLabel(): string {
        // qmllint disable unqualified
        const rows = extremeDeviationBridge.securities
        const selected = extremeDeviationBridge.selected_security_id
        // qmllint enable unqualified
        for (let index = 0; index < rows.length; ++index) {
            if (rows[index].id === selected) {
                return rows[index].name
            }
        }
        return "选择一只有效证券"
    }

    Component.onCompleted: {
        // qmllint disable unqualified
        extremeDeviationBridge.load_support_data()
        extremeDeviationBridge.refresh_latest_trading_day()
        // qmllint enable unqualified
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        GlassPanel {
            id: configPanel
            objectName: "extremeConfigPanel"
            visible: !view.compactLiveFocus
            Layout.fillWidth: true
            Layout.preferredHeight: 326

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "运行配置"
                        color: Theme.text
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        implicitWidth: readinessText.implicitWidth + 24
                        implicitHeight: 30
                        radius: 15
                        color: {
                            // qmllint disable unqualified
                            if (extremeDeviationBridge.running) {
                                return Theme.accentSoft
                            }
                            return extremeDeviationBridge.can_start
                                ? Theme.successSoft : Theme.field
                            // qmllint enable unqualified
                        }
                        RowLayout {
                            anchors.centerIn: parent
                            spacing: 6
                            BusySpinner {
                                Layout.preferredWidth: 14
                                Layout.preferredHeight: 14
                                // qmllint disable unqualified
                                running: view.preparing
                                    || extremeDeviationBridge.running
                                visible: running
                                // qmllint enable unqualified
                            }
                            Text {
                                id: readinessText
                                text: {
                                    // qmllint disable unqualified
                                    if (extremeDeviationBridge.running) {
                                        return "正在复盘"
                                    }
                                    if (view.preparing) {
                                        return "正在准备"
                                    }
                                    return extremeDeviationBridge.can_start
                                        ? "可以开始" : "等待配置"
                                    // qmllint enable unqualified
                                }
                                color: Theme.secondaryText
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        spacing: 5
                        Text {
                            text: "复盘证券"
                            color: Theme.secondaryText
                            font.pixelSize: 11
                        }
                        SearchablePicker {
                            objectName: "extremeSecurityPicker"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 54
                            valueText: view.securityLabel()
                            // qmllint disable unqualified
                            model: extremeDeviationBridge.securities
                            loading: extremeDeviationBridge.securities_loading
                            enabled: !extremeDeviationBridge.running
                            // qmllint enable unqualified
                            emptyText: "全局证券库还没有可复盘证券"
                            onOpening: {
                                // qmllint disable unqualified
                                extremeDeviationBridge.load_support_data()
                                // qmllint enable unqualified
                            }
                            onSelected: value => {
                                // qmllint disable unqualified
                                extremeDeviationBridge.select_security(value)
                                // qmllint enable unqualified
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        spacing: 5
                        Text {
                            text: "复盘日期 · 休市自动探测前后 4 个工作日"
                            color: Theme.secondaryText
                            font.pixelSize: 11
                        }
                        DatePickerField {
                            objectName: "extremeEndDatePicker"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 54
                            // qmllint disable unqualified
                            dateValue: extremeDeviationBridge.end_date
                            maximumDate:
                                extremeDeviationBridge.maximum_historical_date
                            loading: extremeDeviationBridge.calendar_loading
                            enabled: !extremeDeviationBridge.running
                            onDateSelected: value =>
                                extremeDeviationBridge.set_end_date(value)
                            // qmllint enable unqualified
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Text {
                        text: "复盘周期"
                        color: Theme.secondaryText
                        font.pixelSize: 10
                    }
                    Repeater {
                        // qmllint disable unqualified
                        model: extremeDeviationBridge.interval_options
                        // qmllint enable unqualified
                        ChoiceChip {
                            required property var modelData
                            text: modelData.label
                            checked: Boolean(modelData.selected)
                            // qmllint disable unqualified
                            enabled: !extremeDeviationBridge.running
                            // qmllint enable unqualified
                            onToggled: {
                                // qmllint disable unqualified
                                if (!extremeDeviationBridge.set_interval_selected(
                                    String(modelData.value), checked)) {
                                    checked = true
                                }
                                // qmllint enable unqualified
                            }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        // qmllint disable unqualified
                        text: extremeDeviationBridge.date_resolution_text
                        // qmllint enable unqualified
                        color: Theme.accent
                        font.pixelSize: 10
                    }
                }

                Text {
                    text: "只请求已选周期；至少保留一个。优先读取本机 K 线缓存，缺口由供应商补齐，再用本地修正版公式计算。"
                    color: Theme.secondaryText
                    font.pixelSize: 10
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 9

                    GlassMetric {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        label: "复盘证券"
                        // qmllint disable unqualified
                        value: String(extremeDeviationBridge.member_count)
                        // qmllint enable unqualified
                    }
                    GlassMetric {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        label: "已选周期"
                        // qmllint disable unqualified
                        value: String(extremeDeviationBridge.selected_interval_count)
                        // qmllint enable unqualified
                    }
                    GlassMetric {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        label: "预计任务"
                        // qmllint disable unqualified
                        value: String(extremeDeviationBridge.combination_count)
                        // qmllint enable unqualified
                    }
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "取消"
                        // qmllint disable unqualified
                        visible: extremeDeviationBridge.running
                        enabled: extremeDeviationBridge.running
                        onClicked: extremeDeviationBridge.cancel()
                        // qmllint enable unqualified
                    }
                    GlassButton {
                        implicitWidth: 126
                        text: {
                            // qmllint disable unqualified
                            if (extremeDeviationBridge.running) {
                                return "复盘进行中"
                            }
                            return view.preparing ? "正在准备" : "开始复盘"
                            // qmllint enable unqualified
                        }
                        primary: true
                        // qmllint disable unqualified
                        visible: !extremeDeviationBridge.outcome_visible
                            || !extremeDeviationBridge.outcome_primary_action
                        enabled: extremeDeviationBridge.can_start
                        onClicked: extremeDeviationBridge.start()
                        // qmllint enable unqualified
                    }
                }
            }
        }

        GlassPanel {
            objectName: "extremeProgressPanel"
            Layout.fillWidth: true
            Layout.fillHeight: false
            Layout.preferredHeight: view.showLiveStatus ? 220 : 72
            Layout.maximumHeight: view.showLiveStatus ? 220 : 72
            clip: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 10

                RowLayout {
                    visible: !outcomeCard.present
                    Layout.fillWidth: true
                    Text {
                        text: "执行进度"
                        color: Theme.text
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        horizontalAlignment: Text.AlignRight
                        // qmllint disable unqualified
                        text: extremeDeviationBridge.can_start
                            ? "准备完成 · 点击开始复盘"
                            : extremeDeviationBridge.status_text
                        // qmllint enable unqualified
                        color: Theme.secondaryText
                        font.pixelSize: 10
                        elide: Text.ElideLeft
                    }
                }

                RunOutcomeCard {
                    id: outcomeCard
                    objectName: "extremeOutcomeCard"
                    Layout.fillWidth: true
                    Layout.preferredHeight: implicitHeight
                    // qmllint disable unqualified
                    running: extremeDeviationBridge.running
                    recoveryVisible: extremeDeviationBridge.recovery_visible
                    recoveryTone: extremeDeviationBridge.recovery_tone
                    recoveryMessage: extremeDeviationBridge.recovery_message
                    retryCount: extremeDeviationBridge.retry_count
                    waitSeconds: extremeDeviationBridge.wait_seconds
                    activeConcurrency: extremeDeviationBridge.active_concurrency
                    outcomeVisible: extremeDeviationBridge.outcome_visible
                    outcomeTone: extremeDeviationBridge.outcome_tone
                    outcomeTitle: extremeDeviationBridge.outcome_title
                    outcomeSummary: extremeDeviationBridge.outcome_summary
                    primaryAction: extremeDeviationBridge.outcome_primary_action
                    primaryLabel: extremeDeviationBridge.outcome_primary_label
                    failureCount: extremeDeviationBridge.failure_count
                    runningReason: extremeDeviationBridge.status_text
                    progress: extremeDeviationBridge.progress
                    // qmllint enable unqualified
                    runningTitle: "执行进度"
                    onPrimaryActionRequested:
                        action => view.handleOutcomeAction(action)
                    onDetailsRequested: {
                        // qmllint disable unqualified
                        failureDetail.openWithSnapshot(extremeDeviationBridge.failure_groups)
                        // qmllint enable unqualified
                    }
                }

                SmoothProgressBar {
                    visible: outcomeCard.present
                    Layout.fillWidth: true
                    Layout.preferredHeight: 7
                    // qmllint disable unqualified
                    progress: extremeDeviationBridge.progress
                    // qmllint enable unqualified
                }

                StageStrip {
                    visible: outcomeCard.present
                    Layout.fillWidth: true
                    stages: view.stageNames
                    // qmllint disable unqualified
                    activeIndex: extremeDeviationBridge.active_stage
                    progress: extremeDeviationBridge.progress
                    // qmllint enable unqualified
                }

                RowLayout {
                    visible: outcomeCard.present
                    Layout.fillWidth: true
                    spacing: 9
                    GlassMetric {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 62
                        label: "完整命中"
                        // qmllint disable unqualified
                        value: String(extremeDeviationBridge.cache_hits)
                        // qmllint enable unqualified
                    }
                    GlassMetric {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 62
                        label: "服务端计算"
                        // qmllint disable unqualified
                        value: String(extremeDeviationBridge.fetched)
                        // qmllint enable unqualified
                    }
                    GlassMetric {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 62
                        label: "失败"
                        // qmllint disable unqualified
                        value: String(extremeDeviationBridge.failure_count)
                        // qmllint enable unqualified
                    }
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        visible: view.compactLiveFocus
                            && !outcomeCard.running
                        text: "调整配置"
                        onClicked: view.compactConfigExpanded = true
                    }
                    GlassButton {
                        visible: view.compactLiveFocus
                            && outcomeCard.running
                        text: "取消"
                        // qmllint disable unqualified
                        onClicked: extremeDeviationBridge.cancel()
                        // qmllint enable unqualified
                    }
                }
            }
        }

        Item {
            objectName: "extremeIdleSpacer"
            Layout.fillHeight: true
        }
    }

    BudgetConfirmOverlay {
        // qmllint disable unqualified
        visible: extremeDeviationBridge.requires_budget_confirmation
        memberCount: extremeDeviationBridge.member_count
        dimensionCount: extremeDeviationBridge.selected_interval_count
        totalTasks: extremeDeviationBridge.estimated_total
        cacheHits: extremeDeviationBridge.estimated_cache_hits
        coldRequests: extremeDeviationBridge.estimated_cold_requests
        dataPath: extremeDeviationBridge.data_path
        quotaNotice: extremeDeviationBridge.quota_notice
        quotaRemaining: extremeDeviationBridge.quota_remaining
        quotaNewSymbols: extremeDeviationBridge.quota_new_symbols
        quotaShortfall: extremeDeviationBridge.quota_shortfall
        futuSerialNotice: extremeDeviationBridge.futu_serial_notice
        onConfirmRequested:
            extremeDeviationBridge.confirm_budget_and_start()
        onYahooRequested:
            extremeDeviationBridge.use_yahoo_for_budget_and_start()
        onDismissRequested:
            extremeDeviationBridge.dismiss_budget_confirmation()
        // qmllint enable unqualified
    }

    FallbackConfirmOverlay {
        // qmllint disable unqualified
        gate: extremeDeviationBridge.fallback_gate
        // qmllint enable unqualified
        onSettingsRequested: view.networkSettingsRequested()
    }

    FailureDetailOverlay {
        id: failureDetail
        objectName: "extremeFailureDetailOverlay"
        anchors.fill: parent
    }

    Connections {
        // qmllint disable unqualified
        target: extremeDeviationBridge
        // qmllint enable unqualified
        function onChanged(): void {
            // qmllint disable unqualified
            if (extremeDeviationBridge.running) {
                // qmllint enable unqualified
                view.compactConfigExpanded = false
            }
        }
    }
}
