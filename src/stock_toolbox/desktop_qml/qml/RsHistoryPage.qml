pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."
import "components"

Item {
    id: page
    objectName: "rsHistoryPage"

    property bool showClassifications: true
    property bool reportDialogOpen: false
    readonly property bool modalOverlayOpen: reportDialogOpen
    // qmllint disable unqualified
    readonly property string reportErrorText: rsHistoryBridge.report_error
    // qmllint enable unqualified

    function percent(value): string {
        if (value === null || value === undefined) {
            return "—"
        }
        const number = Number(value) * 100
        return (number > 0 ? "+" : "") + number.toFixed(1) + "%"
    }

    function rsText(value): string {
        if (value === null || value === undefined) {
            return "—"
        }
        const number = Number(value)
        return (number > 0 ? "+" : "") + number.toFixed(2)
    }

    FileDialog {
        id: exportDialog
        fileMode: FileDialog.SaveFile
        nameFilters: ["RS 统计表格 ZIP (*.zip)"]
        defaultSuffix: "zip"
        onAccepted: {
            // qmllint disable unqualified
            rsHistoryBridge.export_history(
                rsHistoryBridge.selected_summary.runId,
                "csv",
                selectedFile.toString())
            // qmllint enable unqualified
        }
    }

    Connections {
        // qmllint disable unqualified
        target: rsHistoryBridge
        // qmllint enable unqualified
        function onReport_finished(): void {
            // qmllint disable unqualified
            if (rsHistoryBridge.report_text) {
                page.reportDialogOpen = true
            }
            // qmllint enable unqualified
        }
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
                    text: "RS 历史与结果"
                    color: Theme.text
                    font.pixelSize: 25
                    font.weight: Font.Bold
                }
                Text {
                    text: "冻结结果按区间查看；默认保留最新十条。"
                    color: Theme.secondaryText
                    font.pixelSize: 12
                }
            }
            Item { Layout.fillWidth: true }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            GlassPanel {
                Layout.preferredWidth: 244
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 13
                    spacing: 9

                    Text {
                        text: "最近记录"
                        color: Theme.text
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 7
                        clip: true
                        // qmllint disable unqualified
                        model: rsHistoryBridge.history
                        // qmllint enable unqualified

                        delegate: Rectangle {
                            id: historyRow
                            required property var modelData
                            width: ListView.view.width
                            height: 66
                            radius: 13
                            color: historyMouse.containsMouse
                                ? Theme.accentSoft : Theme.field
                            border.width: 1
                            border.color: Theme.hairline

                            Column {
                                anchors.left: parent.left
                                anchors.leftMargin: 12
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 4
                                Text {
                                    width: parent.width
                                    text: (historyRow.modelData.pinned ? "● " : "")
                                        + historyRow.modelData.name
                                    color: Theme.text
                                    font.pixelSize: 11
                                    font.weight: Font.Medium
                                    elide: Text.ElideRight
                                }
                                Text {
                                    width: parent.width
                                    text: historyRow.modelData.watchlist + " · "
                                        + historyRow.modelData.memberCount + " 位成员"
                                    color: Theme.secondaryText
                                    font.pixelSize: 9
                                    elide: Text.ElideRight
                                }
                            }
                            MouseArea {
                                id: historyMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: {
                                    // qmllint disable unqualified
                                    rsHistoryBridge.select_run(
                                        historyRow.modelData.runId)
                                    // qmllint enable unqualified
                                }
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 10

                GlassPanel {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 134

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 13
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                // qmllint disable unqualified
                                text: rsHistoryBridge.selected_summary.name
                                    || "选择一条历史记录"
                                // qmllint enable unqualified
                                color: Theme.text
                                font.pixelSize: 16
                                font.weight: Font.DemiBold
                            }
                            Item { Layout.fillWidth: true }
                            GlassButton {
                                // qmllint disable unqualified
                                visible: Boolean(
                                    rsHistoryBridge.selected_summary.runId)
                                text: rsHistoryBridge.selected_summary.pinned
                                    ? "取消固定" : "固定"
                                onClicked: rsHistoryBridge.update_history(
                                    rsHistoryBridge.selected_summary.runId,
                                    rsHistoryBridge.selected_summary.name,
                                    rsHistoryBridge.selected_summary.note,
                                    !rsHistoryBridge.selected_summary.pinned)
                                // qmllint enable unqualified
                            }
                            GlassButton {
                                text: "导出表格"
                                // qmllint disable unqualified
                                enabled: Boolean(
                                    rsHistoryBridge.selected_summary.runId)
                                // qmllint enable unqualified
                                onClicked: {
                                    // qmllint disable unqualified
                                    exportDialog.currentFile = rsHistoryBridge.export_default_url
                                    // qmllint enable unqualified
                                    exportDialog.open()
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Repeater {
                                model: [
                                    ["股票池", "watchlist"],
                                    ["基准", "benchmark"],
                                    ["成员", "memberCount"],
                                    ["有效", "validCount"],
                                    ["失败", "failedCount"]
                                ]
                                delegate: Item {
                                    id: metricCell
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 38
                                    Column {
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 3
                                        Text {
                                            text: metricCell.modelData[0]
                                            color: Theme.faintText
                                            font.pixelSize: 8
                                        }
                                        Text {
                                            // qmllint disable unqualified
                                            text: String(
                                                rsHistoryBridge.selected_summary[
                                                    metricCell.modelData[1]] ?? "—")
                                            // qmllint enable unqualified
                                            color: Theme.text
                                            font.pixelSize: 11
                                            font.weight: Font.DemiBold
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            // qmllint disable unqualified
                            text: rsHistoryBridge.selected_summary.provider
                                ? "行情来源："
                                    + rsHistoryBridge.selected_summary.provider
                                    + " · 请求 "
                                    + rsHistoryBridge.selected_summary
                                        .requestedDateWindow
                                    + " · 实际 "
                                    + rsHistoryBridge.selected_summary
                                        .actualDateWindow
                                : ""
                            // qmllint enable unqualified
                            color: Theme.faintText
                            font.pixelSize: 9
                            elide: Text.ElideRight
                        }
                    }
                }

                GlassPanel {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 13
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true
                            ChoiceChip {
                                text: "分类综合"
                                checked: page.showClassifications
                                onToggled: {
                                    if (checked) {
                                        page.showClassifications = true
                                    }
                                }
                            }
                            ChoiceChip {
                                text: "个股明细"
                                checked: !page.showClassifications
                                onToggled: {
                                    if (checked) {
                                        page.showClassifications = false
                                    }
                                }
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                visible: !page.showClassifications
                                text: "每次只查看一个区间"
                                color: Theme.faintText
                                font.pixelSize: 9
                            }
                        }

                        RowLayout {
                            visible: !page.showClassifications
                            Layout.fillWidth: true
                            Layout.preferredHeight: visible ? 34 : 0
                            spacing: 7
                            Repeater {
                                // qmllint disable unqualified
                                model: rsHistoryBridge.ranges
                                // qmllint enable unqualified
                                delegate: ChoiceChip {
                                    required property var modelData
                                    text: modelData.displayLabel
                                    // qmllint disable unqualified
                                    checked: modelData.id
                                        === rsHistoryBridge.selected_range_id
                                    onToggled: {
                                        if (checked) {
                                            rsHistoryBridge.select_range(
                                                modelData.id)
                                        }
                                    }
                                    // qmllint enable unqualified
                                }
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                // qmllint disable unqualified
                                text: rsHistoryBridge.selected_range_summary
                                    .benchmark
                                    ? rsHistoryBridge.selected_range_summary
                                        .benchmark + " · 基准收益 "
                                        + page.percent(
                                            rsHistoryBridge
                                                .selected_range_summary
                                                .benchmarkReturn)
                                    : ""
                                // qmllint enable unqualified
                                color: Theme.secondaryText
                                font.pixelSize: 9
                                font.weight: Font.Medium
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 20
                            spacing: 8
                            Text {
                                text: page.showClassifications
                                    ? "分类" : "证券 / 公司"
                                color: Theme.faintText
                                font.pixelSize: 9
                                Layout.fillWidth: true
                            }
                            Text {
                                visible: !page.showClassifications
                                text: "当前参评分类"
                                color: Theme.faintText
                                font.pixelSize: 9
                                Layout.preferredWidth: 126
                            }
                            Text {
                                visible: !page.showClassifications
                                text: "个股收益"
                                color: Theme.faintText
                                font.pixelSize: 9
                                horizontalAlignment: Text.AlignRight
                                Layout.preferredWidth: 68
                            }
                            Text {
                                visible: page.showClassifications
                                text: "状态"
                                color: Theme.faintText
                                font.pixelSize: 9
                                horizontalAlignment: Text.AlignRight
                                Layout.preferredWidth: 112
                            }
                            Text {
                                visible: page.showClassifications
                                text: "综合分"
                                color: Theme.faintText
                                font.pixelSize: 9
                                horizontalAlignment: Text.AlignRight
                                Layout.preferredWidth: 58
                            }
                            Button {
                                id: rsSortButton
                                objectName: "rsSortButton"
                                visible: !page.showClassifications
                                Layout.preferredWidth: 90
                                Layout.preferredHeight: 20
                                hoverEnabled: true
                                // qmllint disable unqualified
                                text: rsHistoryBridge.stock_sort_descending
                                    ? "RS  强 → 弱" : "RS  弱 → 强"
                                onClicked: rsHistoryBridge.toggle_stock_sort()
                                // qmllint enable unqualified
                                contentItem: Text {
                                    text: rsSortButton.text
                                    color: rsSortButton.hovered
                                        ? Theme.accent : Theme.faintText
                                    font.pixelSize: 9
                                    font.weight: Font.DemiBold
                                    horizontalAlignment: Text.AlignRight
                                    verticalAlignment: Text.AlignVCenter
                                }
                                background: Rectangle {
                                    radius: 8
                                    color: rsSortButton.hovered
                                        ? Theme.accentSoft : "transparent"
                                }
                            }
                        }

                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 6
                            // qmllint disable unqualified
                            model: page.showClassifications
                                ? rsHistoryBridge.classification_results
                                : rsHistoryBridge.stock_results
                            // qmllint enable unqualified

                            delegate: Rectangle {
                                id: resultRow
                                required property var modelData
                                width: ListView.view.width
                                height: 46
                                radius: 11
                                color: Theme.field
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 11
                                    anchors.rightMargin: 11
                                    spacing: 8
                                    Column {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text {
                                            width: parent.width
                                            text: page.showClassifications
                                                ? resultRow.modelData.name
                                                : resultRow.modelData.symbol
                                            color: Theme.text
                                            font.pixelSize: 11
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            visible: !page.showClassifications
                                            width: parent.width
                                            text: resultRow.modelData.companyName
                                                || ""
                                            color: Theme.secondaryText
                                            font.pixelSize: 8
                                            elide: Text.ElideRight
                                        }
                                    }
                                    Text {
                                        visible: !page.showClassifications
                                        text: resultRow.modelData.classification
                                            || ""
                                        color: Theme.secondaryText
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                        Layout.preferredWidth: 126
                                    }
                                    Text {
                                        visible: !page.showClassifications
                                        text: page.percent(
                                            resultRow.modelData.stockReturn)
                                        color: Theme.secondaryText
                                        font.pixelSize: 10
                                        horizontalAlignment: Text.AlignRight
                                        Layout.preferredWidth: 68
                                    }
                                    RowLayout {
                                        visible: page.showClassifications
                                        Layout.preferredWidth: 112
                                        spacing: 5
                                        Text {
                                            Layout.fillWidth: true
                                            text: page.showClassifications
                                                ? resultRow.modelData.statusLabel
                                                : ""
                                            color: Theme.secondaryText
                                            font.pixelSize: 10
                                            font.weight: Font.DemiBold
                                            horizontalAlignment: Text.AlignRight
                                        }
                                        InfoTip {
                                            objectName: "classificationStatusHelp"
                                            visible: page.showClassifications
                                                && resultRow.modelData
                                                    .statusHelpVisible
                                            title: "状态判断依据"
                                            tipText: page.showClassifications
                                                ? resultRow.modelData
                                                    .statusExplanation
                                                : ""
                                            preferredWidth: 350
                                            openLeft: true
                                            openAbove: true
                                        }
                                    }
                                    Text {
                                        visible: !page.showClassifications
                                        text: page.rsText(
                                            resultRow.modelData.rs)
                                        color: Theme.accent
                                        font.pixelSize: 10
                                        font.weight: Font.DemiBold
                                        horizontalAlignment: Text.AlignRight
                                        Layout.preferredWidth: 90
                                    }
                                    Text {
                                        visible: page.showClassifications
                                        // Stock rows share this delegate but do not have a
                                        // classification-only score projection.
                                        text: resultRow.modelData.scoreText || ""
                                        color: Theme.accent
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                        horizontalAlignment: Text.AlignRight
                                        Layout.preferredWidth: 58
                                    }
                                }
                            }
                        }

                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            // qmllint disable unqualified
                            visible: Boolean(
                                rsHistoryBridge.selected_summary.runId)
                                && (page.showClassifications
                                    ? rsHistoryBridge.classification_results.length
                                    : rsHistoryBridge.stock_results.length) === 0
                            // qmllint enable unqualified
                            text: page.showClassifications
                                ? "本次没有可用的分类综合结果。"
                                : "当前区间没有可用的个股结果。"
                            color: Theme.faintText
                            font.pixelSize: 10
                        }
                    }
                }

                GlassPanel {
                    objectName: "rsAIReportCard"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 88

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 13
                        spacing: 10

                        ColumnLayout {
                            Layout.fillWidth: true
                            Text {
                                text: "AI 强弱解读"
                                color: Theme.text
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                // qmllint disable unqualified
                                text: !rsHistoryBridge.selected_summary.runId
                                    ? "选择历史记录后可以生成复盘结论"
                                    : rsHistoryBridge.report_error
                                    || (rsHistoryBridge.report_running
                                        ? "AI 正在整理强弱证据…"
                                        : rsHistoryBridge.report_text
                                        ? "解读已保存，点击打开独立阅读窗口"
                                        : !rsHistoryBridge.ai_configured
                                        ? "AI 尚未配置，RS 结果仍可正常查看"
                                        : "按需生成，不会修改 RS 分数")
                                // qmllint enable unqualified
                                color: page.reportErrorText
                                    ? Theme.danger : Theme.secondaryText
                                font.pixelSize: 10
                                elide: Text.ElideRight
                            }
                        }

                        BusySpinner {
                            // qmllint disable unqualified
                            visible: rsHistoryBridge.report_running
                            running: visible
                            // qmllint enable unqualified
                        }
                        GlassButton {
                            // qmllint disable unqualified
                            visible: Boolean(
                                rsHistoryBridge.selected_summary.runId)
                                && !rsHistoryBridge.ai_configured
                            // qmllint enable unqualified
                            text: "前往设置"
                            // qmllint disable unqualified
                            onClicked: shellBridge.open_settings()
                            // qmllint enable unqualified
                        }
                        GlassButton {
                            // qmllint disable unqualified
                            visible: Boolean(
                                rsHistoryBridge.selected_summary.runId)
                                && rsHistoryBridge.ai_configured
                            enabled: !rsHistoryBridge.report_running
                            text: rsHistoryBridge.report_text
                                ? "查看 AI 解读" : "生成 AI 解读"
                            onClicked: {
                                if (rsHistoryBridge.report_text) {
                                    page.reportDialogOpen = true
                                } else {
                                    rsHistoryBridge.generate_report()
                                }
                            }
                            // qmllint enable unqualified
                        }
                    }
                }
            }
        }
    }

    RsAIReportOverlay {
        anchors.fill: parent
        visible: page.reportDialogOpen
        // qmllint disable unqualified
        reportText: rsHistoryBridge.report_text
        running: rsHistoryBridge.report_running
        // qmllint enable unqualified
        onCloseRequested: page.reportDialogOpen = false
        onRegenerateRequested: {
            // qmllint disable unqualified
            rsHistoryBridge.generate_report()
            // qmllint enable unqualified
        }
    }
}
