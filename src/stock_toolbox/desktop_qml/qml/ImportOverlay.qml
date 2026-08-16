pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."
import "components"

Rectangle {
    id: overlay
    objectName: "importOverlay"
    // Keep modal content above pages while preserving native title-bar controls.
    z: 50
    signal closeRequested
    property string detailFilter: ""
    property bool filePreviewApplied: false
    property bool importLaunchPending: false

    opacity: visible ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    function finishAndClear(): void {
        // qmllint disable unqualified
        if (!masterDataBridge.reset_import_session())
            return
        // qmllint enable unqualified
        importText.clear()
        manualTicker.clear()
        overlay.detailFilter = ""
        overlay.filePreviewApplied = false
        overlay.importLaunchPending = false
        overlay.closeRequested()
    }

    Connections {
        // qmllint disable unqualified
        target: masterDataBridge
        // qmllint enable unqualified
        function onImport_finished(): void {
            overlay.importLaunchPending = false
        }
    }

    function visibleDetails(): var {
        // qmllint disable unqualified
        const rows = masterDataBridge.import_details
        // qmllint enable unqualified
        return overlay.detailFilter
            ? rows.filter(row => row.category === overlay.detailFilter)
            : rows
    }

    function statusLabel(status): string {
        return {
            "IMPORTED": "导入成功",
            "IMPORTED_PENDING_CLASSIFICATION": "成功 · 待分类",
            "EXISTING": "已存在 / 跳过",
            "INVALID_INPUT": "输入无效",
            "UNAVAILABLE": "资料获取失败",
            "FAILED": "资料获取失败",
            "EXCLUDED": "排除资产",
            "DUPLICATE": "批内重复 / 跳过"
        }[status] || status
    }

    FileDialog {
        id: csvDialog
        fileMode: FileDialog.OpenFile
        nameFilters: ["CSV / 文本 (*.csv *.txt)", "所有文件 (*)"]
        onAccepted: {
            overlay.filePreviewApplied = false
            // qmllint disable unqualified
            const content = masterDataBridge.read_import_file(
                selectedFile.toString())
            // qmllint enable unqualified
            if (content) {
                importText.text = importText.text.trim()
                    ? importText.text.trim() + "\n" + content : content
                overlay.filePreviewApplied = true
            }
        }
    }

    color: Theme.modalScrim
    MouseArea { anchors.fill: parent }

    GlassPanel {
        width: Math.min(780, overlay.width - 48)
        height: Math.min(650, overlay.height - 48)
        anchors.centerIn: parent
        color: Theme.dark ? "#F021242A" : "#FFF8F7F4"
        scale: overlay.visible ? 1 : 0.985
        Behavior on scale {
            NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Column {
                    spacing: 4
                    Text {
                        text: "导入美股正股"
                        color: Theme.text
                        font.pixelSize: 22
                        font.weight: Font.Bold
                    }
                    Text {
                        text: "Provider 负责基础资料；AI 优先复用现有中文标签，无法使用时由供应商资料保底。"
                        color: Theme.secondaryText
                        font.pixelSize: 10
                    }
                }
                Item { Layout.fillWidth: true }
                GlassButton {
                    text: "暂时保存"
                    // qmllint disable unqualified
                    enabled: !masterDataBridge.import_running
                    // qmllint enable unqualified
                    onClicked: overlay.closeRequested()
                }
                GlassButton {
                    text: "完成"
                    // qmllint disable unqualified
                    enabled: !masterDataBridge.import_running
                    // qmllint enable unqualified
                    onClicked: overlay.finishAndClear()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                GlassButton {
                    text: "读取 CSV…"
                    // qmllint disable unqualified
                    enabled: !masterDataBridge.import_running
                    // qmllint enable unqualified
                    onClicked: csvDialog.open()
                }
                InfoTip {
                    objectName: "csvFormatHelp"
                    title: "CSV 导入格式"
                    tipText: "可直接读取券商或网站导出的 CSV / TXT，"
                        + "软件会自动识别 ticker / symbol / 股票代码等列。"
                        + "\n支持 UTF-8、GB18030，以及逗号、制表符、"
                        + "分号或竖线分隔。"
                        + "\n若有多个疑似代码列，会展示样例让你选择；"
                        + "不会猜测后直接导入。"
                        + "\n支持 AAPL、AAPL.US、NASDAQ:AAPL，"
                        + "最终仍只导入美股正股。"
                    preferredWidth: 330
                }
                GlassTextInput {
                    id: manualTicker
                    Layout.fillWidth: true
                    placeholderText: "手工追加一只，例如 AAPL"
                    onAccepted: appendButton.clicked()
                }
                GlassButton {
                    id: appendButton
                    text: "追加"
                    enabled: manualTicker.text.trim().length > 0
                    onClicked: {
                        const value = manualTicker.text.trim()
                        importText.text = importText.text.trim()
                            ? importText.text.trim() + "\n" + value : value
                        manualTicker.clear()
                    }
                }
            }

            RowLayout {
                // qmllint disable unqualified
                visible: masterDataBridge.import_file_requires_choice
                // qmllint enable unqualified
                Layout.fillWidth: true
                Layout.preferredHeight: 34
                spacing: 7

                Text {
                    text: "请选择证券代码列"
                    color: Theme.secondaryText
                    font.pixelSize: 10
                }
                Repeater {
                    // qmllint disable unqualified
                    model: masterDataBridge.import_file_candidates
                    // qmllint enable unqualified
                    GlassButton {
                        required property var modelData
                        text: modelData.name + " · "
                            + modelData.samples.slice(0, 2).join(" / ")
                        enabled: !overlay.filePreviewApplied
                        onClicked: {
                            // qmllint disable unqualified
                            if (masterDataBridge.select_import_column(
                                    modelData.index)) {
                                const content =
                                    masterDataBridge.import_file_text
                                importText.text = importText.text.trim()
                                    ? importText.text.trim() + "\n" + content
                                    : content
                                overlay.filePreviewApplied = true
                            }
                            // qmllint enable unqualified
                        }
                    }
                }
                Item { Layout.fillWidth: true }
            }

            RowLayout {
                // qmllint disable unqualified
                visible: Boolean(masterDataBridge.import_preview.column)
                // qmllint enable unqualified
                Layout.fillWidth: true
                Layout.preferredHeight: 20
                spacing: 14

                Text {
                    // qmllint disable unqualified
                    text: "已识别列 · "
                        + masterDataBridge.import_preview.column
                    // qmllint enable unqualified
                    color: Theme.accent
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }
                Text {
                    // qmllint disable unqualified
                    text: "数据行 " + masterDataBridge.import_preview.rows
                        + " · 有效 "
                        + masterDataBridge.import_preview.recognized
                        + " · 重复 "
                        + masterDataBridge.import_preview.duplicates
                        + " · 无效 "
                        + masterDataBridge.import_preview.invalid
                    // qmllint enable unqualified
                    color: Theme.secondaryText
                    font.pixelSize: 9
                }
                Item { Layout.fillWidth: true }
            }

            ScrollView {
                id: importTickerScroll
                objectName: "importTickerScroll"
                Layout.fillWidth: true
                Layout.preferredHeight: 104
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded
                background: Rectangle {
                    radius: Theme.controlRadius
                    color: Theme.field
                    border.width: 1
                    border.color: importText.activeFocus
                        ? Theme.accent : Theme.hairline
                }

                TextArea {
                    id: importText
                    objectName: "importText"
                    width: importTickerScroll.availableWidth
                    placeholderText: "粘贴代码，每行一个；也支持逗号分隔，例如 IREN, NVDA, AMD"
                    color: Theme.text
                    placeholderTextColor: Theme.faintText
                    wrapMode: TextEdit.Wrap
                    padding: 13
                    enabled: {
                        // qmllint disable unqualified
                        return !masterDataBridge.import_running
                        // qmllint enable unqualified
                    }
                    background: Item {}
                }
            }

            RowLayout {
                Layout.fillWidth: true
                GlassButton {
                    text: overlay.importLaunchPending
                        // qmllint disable unqualified
                        || masterDataBridge.import_running
                        // qmllint enable unqualified
                        ? "正在导入…" : "开始导入"
                    primary: true
                    busy: overlay.importLaunchPending
                        // qmllint disable unqualified
                        || masterDataBridge.import_running
                        // qmllint enable unqualified
                    implicitWidth: 116
                    // qmllint disable unqualified
                    enabled: !overlay.importLaunchPending
                        && !masterDataBridge.import_running
                        && importText.text.trim().length > 0
                    onClicked: {
                        overlay.importLaunchPending = true
                        overlay.detailFilter = ""
                        if (!masterDataBridge.import_securities(
                                importText.text)) {
                            overlay.importLaunchPending = false
                        }
                    }
                    // qmllint enable unqualified
                }
                GlassButton {
                    text: "取消导入"
                    // qmllint disable unqualified
                    visible: masterDataBridge.import_running
                    onClicked: masterDataBridge.cancel_import()
                    // qmllint enable unqualified
                }
                Item { Layout.fillWidth: true }
                Text {
                    // qmllint disable unqualified
                    text: masterDataBridge.import_total > 0
                        ? masterDataBridge.import_completed + " / "
                            + masterDataBridge.import_total
                        : "等待开始"
                    // qmllint enable unqualified
                    color: Theme.text
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    font.family: "Menlo"
                }
            }

            Rectangle {
                objectName: "importProgressPanel"
                Layout.fillWidth: true
                Layout.preferredHeight: 68
                radius: 14
                color: Theme.field
                border.width: 1
                border.color: Theme.hairline

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            // qmllint disable unqualified
                            text: masterDataBridge.import_total === 0
                                ? "尚未开始导入"
                                : masterDataBridge.import_status
                            // qmllint enable unqualified
                            color: Theme.secondaryText
                            font.pixelSize: 10
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        Text {
                            // qmllint disable unqualified
                            text: Math.round(
                                importProgressBar.value * 100) + "%"
                            visible: masterDataBridge.import_total > 0
                            // qmllint enable unqualified
                            color: Theme.faintText
                            font.pixelSize: 10
                        }
                    }
                    ProgressBar {
                        id: importProgressBar
                        objectName: "importProgressBar"
                        Layout.fillWidth: true
                        // qmllint disable unqualified
                        value: masterDataBridge.import_progress
                        // qmllint enable unqualified
                        Behavior on value {
                            NumberAnimation {
                                duration: 520
                                easing.type: Easing.OutCubic
                            }
                        }
                        background: Rectangle {
                            implicitHeight: 7
                            radius: 4
                            color: Theme.accentSoft
                        }
                        contentItem: Item {
                            implicitHeight: 7
                            Rectangle {
                                width: parent.width
                                    * Math.max(0, Math.min(1,
                                        importProgressBar.visualPosition))
                                height: parent.height
                                radius: 4
                                color: Theme.accent
                            }
                        }
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 6
                columnSpacing: 7
                Repeater {
                    model: [
                        ["成功", "success"], ["已存在", "existing"],
                        ["批内重复", "duplicate"], ["资料缺失", "unavailable"],
                        ["非正股", "excluded"], ["输入无效", "invalid"]
                    ]
                    delegate: Rectangle {
                        id: metricCard
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: 54
                        radius: 12
                        color: overlay.detailFilter === modelData[1]
                            ? Theme.accentSoft : Theme.field
                        border.width: 1
                        border.color: Theme.hairline
                        Column {
                            anchors.centerIn: parent
                            spacing: 4
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                // qmllint disable unqualified
                                text: String(masterDataBridge.import_summary[
                                    metricCard.modelData[1]] || 0)
                                // qmllint enable unqualified
                                color: Theme.text
                                font.pixelSize: 15
                                font.weight: Font.DemiBold
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: metricCard.modelData[0]
                                color: Theme.secondaryText
                                font.pixelSize: 9
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: overlay.detailFilter =
                                overlay.detailFilter === metricCard.modelData[1]
                                ? "" : metricCard.modelData[1]
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "逐项结果"
                    color: Theme.text
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: overlay.detailFilter
                        ? "已筛选 · 再次点击统计卡片恢复全部"
                        : "点击统计卡片筛选"
                    color: Theme.faintText
                    font.pixelSize: 9
                }
            }

            Rectangle {
                objectName: "importResultsPanel"
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 14
                color: Theme.field
                border.width: 1
                border.color: Theme.hairline

                ListView {
                    id: resultList
                    anchors.fill: parent
                    anchors.margins: 7
                    clip: true
                    spacing: 5
                    model: overlay.visibleDetails()
                    delegate: Rectangle {
                        id: detailRow
                        required property var modelData
                        width: ListView.view.width
                        height: 38
                        radius: 10
                        color: Theme.panel
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 11
                            anchors.rightMargin: 11
                            Text {
                                text: detailRow.modelData.symbol
                                color: Theme.text
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                                font.family: "Menlo"
                                Layout.preferredWidth: 98
                            }
                            Text {
                                text: overlay.statusLabel(
                                    detailRow.modelData.status)
                                color: Theme.secondaryText
                                font.pixelSize: 10
                                Layout.preferredWidth: 126
                            }
                            Text {
                                text: detailRow.modelData.reason || "—"
                                color: Theme.secondaryText
                                font.pixelSize: 10
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }
                }

                Column {
                    anchors.centerIn: parent
                    spacing: 6
                    visible: resultList.count === 0
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        // qmllint disable unqualified
                        text: masterDataBridge.import_running
                            ? "正在处理，结果会逐项出现"
                            : "结果区为空"
                        // qmllint enable unqualified
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "输入证券代码并开始导入后，可在这里查看每一项状态。"
                        color: Theme.faintText
                        font.pixelSize: 9
                    }
                }
            }
        }
    }
}
