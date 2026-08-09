pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "."
import "components"

Item {
    id: root
    objectName: "classificationMemberOverlay"
    z: 55

    property var classification: null
    property var candidates: []
    property var batchResult: ({})
    property var selectedIds: []
    readonly property bool hasResult: Boolean(
        batchResult && batchResult.details && batchResult.details.length)

    signal closeRequested
    signal submitRequested(var securityIds)

    function filteredCandidates() {
        const normalized = searchInput.text.trim().toLowerCase()
        if (!normalized) {
            return candidates
        }
        return candidates.filter(item =>
            item.displaySymbol.toLowerCase().includes(normalized)
                || item.name.toLowerCase().includes(normalized))
    }

    function toggleSecurity(securityId) {
        const next = selectedIds.slice()
        const index = next.indexOf(securityId)
        if (index >= 0) {
            next.splice(index, 1)
        } else {
            next.push(securityId)
        }
        selectedIds = next
    }

    onVisibleChanged: {
        if (visible) {
            selectedIds = []
            searchInput.clear()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.modalScrim
        MouseArea { anchors.fill: parent }
    }

    GlassPanel {
        width: Math.min(720, parent.width - 36)
        height: Math.min(620, parent.height - 36)
        anchors.centerIn: parent
        color: Theme.dark ? "#F021242A" : "#FFF8F7F4"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                Column {
                    spacing: 4
                    Text {
                        text: root.hasResult ? "批量添加结果" : "批量添加证券"
                        color: Theme.text
                        font.pixelSize: 20
                        font.weight: Font.Bold
                    }
                    Text {
                        text: root.classification
                            ? "添加到标签「" + root.classification.name + "」"
                            : ""
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                }
                Item { Layout.fillWidth: true }
                GlassButton {
                    text: "关闭"
                    onClicked: root.closeRequested()
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: !root.hasResult
                spacing: 12

                GlassTextInput {
                    id: searchInput
                    Layout.fillWidth: true
                    placeholderText: "搜索代码或公司名称"
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "可添加证券"
                        color: Theme.text
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: "已选择 " + root.selectedIds.length + " 只"
                        color: root.selectedIds.length
                            ? Theme.accent : Theme.secondaryText
                        font.pixelSize: 11
                    }
                }

                ListView {
                    id: candidateList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 7
                    clip: true
                    model: root.filteredCandidates()

                    delegate: Rectangle {
                        id: candidateRow
                        required property var modelData
                        readonly property bool selected:
                            root.selectedIds.includes(modelData.id)

                        width: ListView.view.width
                        height: 58
                        radius: 14
                        color: selected ? Theme.accentSoft : Theme.field
                        border.width: 1
                        border.color: selected
                            ? Theme.accent : Theme.hairline

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 13
                            anchors.rightMargin: 13
                            spacing: 11

                            Rectangle {
                                Layout.preferredWidth: 22
                                Layout.preferredHeight: 22
                                radius: 7
                                color: candidateRow.selected
                                    ? Theme.accent : "transparent"
                                border.width: 1
                                border.color: candidateRow.selected
                                    ? Theme.accent : Theme.hairline
                                Text {
                                    anchors.centerIn: parent
                                    text: candidateRow.selected ? "✓" : ""
                                    color: "#FFFFFF"
                                    font.pixelSize: 12
                                    font.weight: Font.Bold
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Text {
                                    text: candidateRow.modelData.displaySymbol
                                        + "  " + candidateRow.modelData.name
                                    color: Theme.text
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }
                                Text {
                                    text: candidateRow.modelData.classificationCount
                                        >= 3
                                        ? "已有 3 个标签，添加时会失败"
                                        : "当前 "
                                            + candidateRow.modelData
                                                .classificationCount
                                            + "/3 个标签"
                                    color: candidateRow.modelData.classificationCount
                                        >= 3 ? Theme.danger : Theme.faintText
                                    font.pixelSize: 10
                                }
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: root.toggleSecurity(
                                candidateRow.modelData.id)
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: candidateList.count === 0
                        text: searchInput.text.trim()
                            ? "没有匹配的证券" : "所有证券都已绑定该标签"
                        color: Theme.faintText
                        font.pixelSize: 11
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: "部分证券失败不会影响其他证券；失败项会逐条说明原因。"
                        color: Theme.faintText
                        font.pixelSize: 10
                        wrapMode: Text.WordWrap
                    }
                    GlassButton {
                        text: "取消"
                        onClicked: root.closeRequested()
                    }
                    GlassButton {
                        text: "添加 " + root.selectedIds.length + " 只证券"
                        primary: true
                        enabled: root.selectedIds.length > 0
                        onClicked: root.submitRequested(root.selectedIds)
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.hasResult
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Repeater {
                        model: [
                            {
                                label: "成功",
                                value: root.batchResult.summary
                                    ? root.batchResult.summary.added : 0
                            },
                            {
                                label: "已存在",
                                value: root.batchResult.summary
                                    ? root.batchResult.summary.existing : 0
                            },
                            {
                                label: "失败",
                                value: root.batchResult.summary
                                    ? root.batchResult.summary.failed : 0
                            }
                        ]
                        delegate: Rectangle {
                            id: summaryCard
                            required property var modelData
                            Layout.fillWidth: true
                            height: 68
                            radius: 14
                            color: Theme.field
                            border.width: 1
                            border.color: Theme.hairline
                            Column {
                                anchors.centerIn: parent
                                spacing: 4
                                Text {
                                    anchors.horizontalCenter:
                                        parent.horizontalCenter
                                    text: summaryCard.modelData.value
                                    color: Theme.text
                                    font.pixelSize: 18
                                    font.weight: Font.Bold
                                }
                                Text {
                                    anchors.horizontalCenter:
                                        parent.horizontalCenter
                                    text: summaryCard.modelData.label
                                    color: Theme.secondaryText
                                    font.pixelSize: 10
                                }
                            }
                        }
                    }
                }

                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 7
                    model: root.batchResult.details || []
                    delegate: Rectangle {
                        id: resultRow
                        required property var modelData
                        width: ListView.view.width
                        height: 54
                        radius: 13
                        color: Theme.field
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 13
                            anchors.rightMargin: 13
                            spacing: 10
                            Text {
                                text: resultRow.modelData.symbol
                                    + "  " + resultRow.modelData.name
                                color: Theme.text
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }
                            Text {
                                text: resultRow.modelData.reason
                                color: resultRow.modelData.category === "failed"
                                    ? Theme.danger
                                    : (resultRow.modelData.category === "added"
                                        ? Theme.success
                                        : Theme.secondaryText)
                                font.pixelSize: 10
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: "有效证券已经写入标签，失败证券保持原状。"
                        color: Theme.faintText
                        font.pixelSize: 10
                    }
                    GlassButton {
                        text: "完成"
                        primary: true
                        onClicked: root.closeRequested()
                    }
                }
            }
        }
    }
}
