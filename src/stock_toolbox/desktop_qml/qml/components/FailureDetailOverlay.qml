pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import ".."

FocusScope {
    id: overlay
    objectName: "failureDetailOverlay"

    property var snapshotModel: []
    property var expandedCodes: ({})
    property Item previousFocusItem: null

    signal closeRequested()

    z: 1100
    visible: false
    opacity: visible ? 1 : 0
    Accessible.role: Accessible.Dialog
    Accessible.name: "失败详情"

    function containsFocusItem(item): bool {
        let current = item
        while (current) {
            if (current === overlay) {
                return true
            }
            current = current.parent
        }
        return false
    }

    function moveModalFocus(forward): void {
        const activeWindow = overlay.Window.window
        let candidate = activeWindow ? activeWindow.activeFocusItem : null
        for (let step = 0; candidate && step < 128; ++step) {
            candidate = candidate.nextItemInFocusChain(forward)
            if (overlay.containsFocusItem(candidate)) {
                candidate.forceActiveFocus(
                    forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
                return
            }
        }
        failureDetailCloseButton.forceActiveFocus()
    }

    function openWithSnapshot(groups): void {
        const frozen = []
        for (let index = 0; index < groups.length; ++index) {
            const group = groups[index]
            frozen.push({
                "code": String(group.code || ""),
                "count": Math.max(0, Number(group.count || 0)),
                "symbols": Array.from(group.symbols || []),
                "intervals": Array.from(group.intervals || [])
            })
        }
        if (frozen.length === 0) {
            return
        }
        snapshotModel = frozen
        expandedCodes = ({})
        visible = true
    }

    function dismiss(): void {
        visible = false
        closeRequested()
    }

    function toggleExpanded(code): void {
        const next = Object.assign({}, expandedCodes)
        next[code] = !Boolean(next[code])
        expandedCodes = next
    }

    onVisibleChanged: {
        if (visible) {
            const activeWindow = overlay.Window.window
            previousFocusItem = activeWindow
                ? activeWindow.activeFocusItem : null
            Qt.callLater(() =>
                failureDetailCloseButton.forceActiveFocus())
        } else if (previousFocusItem) {
            const restoreTarget = previousFocusItem
            previousFocusItem = null
            Qt.callLater(() => restoreTarget.forceActiveFocus())
        }
    }
    Keys.onEscapePressed: overlay.dismiss()
    Keys.onTabPressed: event => {
        overlay.moveModalFocus(true)
        event.accepted = true
    }
    Keys.onBacktabPressed: event => {
        overlay.moveModalFocus(false)
        event.accepted = true
    }

    Behavior on opacity {
        NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.modalScrim

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onWheel: wheel => wheel.accepted = true
        }
    }

    GlassPanel {
        id: detailPanel
        objectName: "failureDetailPanel"
        anchors.centerIn: parent
        width: Math.min(620, overlay.width - 36)
        height: Math.min(510, overlay.height - 36)
        color: Theme.overlayPanel
        scale: overlay.visible ? 1 : 0.985

        Behavior on scale {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12

            RowLayout {
                Layout.fillWidth: true

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text {
                        text: "失败详情"
                        color: Theme.text
                        font.pixelSize: 19
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: "按稳定原因归组；展开后仅显示受影响证券与周期。"
                        color: Theme.secondaryText
                        font.pixelSize: 10
                    }
                }

                GlassButton {
                    id: failureDetailCloseButton
                    objectName: "failureDetailCloseButton"
                    text: "关闭"
                    Accessible.role: Accessible.Button
                    Accessible.name: "关闭失败详情"
                    onClicked: overlay.dismiss()
                    Keys.onTabPressed: event => {
                        overlay.moveModalFocus(true)
                        event.accepted = true
                    }
                    Keys.onBacktabPressed: event => {
                        overlay.moveModalFocus(false)
                        event.accepted = true
                    }
                }
            }

            ListView {
                id: groupList
                objectName: "failureGroupList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 8
                clip: true
                model: overlay.snapshotModel
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                delegate: Rectangle {
                    id: groupRow
                    objectName: "failureGroupRow"
                    required property var modelData

                    readonly property bool expanded:
                        Boolean(overlay.expandedCodes[modelData.code])

                    width: ListView.view.width
                    implicitHeight: groupContent.implicitHeight + 16
                    height: implicitHeight
                    radius: 13
                    color: Theme.field
                    border.width: 1
                    border.color: activeFocus
                        ? Theme.accent : Theme.hairline
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: modelData.code + "，"
                        + (expanded ? "收起影响范围" : "展开影响范围")

                    ColumnLayout {
                        id: groupContent
                        anchors.fill: parent
                        anchors.leftMargin: 13
                        anchors.rightMargin: 13
                        anchors.topMargin: 8
                        anchors.bottomMargin: 8
                        spacing: 5

                        RowLayout {
                            id: groupHeader
                            Layout.fillWidth: true
                            Text {
                                text: groupRow.modelData.code
                                color: Theme.text
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                            Rectangle {
                                implicitWidth: countLabel.implicitWidth + 14
                                implicitHeight: 22
                                radius: 11
                                color: Theme.dangerSoft
                                Text {
                                    id: countLabel
                                    anchors.centerIn: parent
                                    text: String(groupRow.modelData.count)
                                    color: Theme.danger
                                    font.pixelSize: 9
                                    font.weight: Font.DemiBold
                                }
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: groupRow.expanded ? "收起" : "展开影响范围"
                                color: Theme.accent
                                font.pixelSize: 10
                            }
                        }

                        TextEdit {
                            objectName: "failureEvidenceText"
                            visible: groupRow.expanded
                            Layout.fillWidth: true
                            Layout.preferredHeight: contentHeight
                            text: {
                                const symbols = groupRow.modelData.symbols
                                const intervals = groupRow.modelData.intervals
                                const symbolText = symbols.length > 0
                                    ? symbols.join(" · ") : "无证券标识"
                                const intervalText = intervals.length > 0
                                    ? intervals.join(" · ") : "无周期标识"
                                return "证券  " + symbolText
                                    + "\n周期  " + intervalText
                            }
                            color: Theme.secondaryText
                            font.pixelSize: 9
                            readOnly: true
                            selectByMouse: true
                            persistentSelection: true
                            wrapMode: TextEdit.Wrap
                        }
                    }

                    MouseArea {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: groupHeader.height + 16
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            groupRow.forceActiveFocus()
                            overlay.toggleExpanded(groupRow.modelData.code)
                        }
                    }

                    Keys.onReturnPressed:
                        overlay.toggleExpanded(groupRow.modelData.code)
                    Keys.onEnterPressed:
                        overlay.toggleExpanded(groupRow.modelData.code)
                    Keys.onSpacePressed:
                        overlay.toggleExpanded(groupRow.modelData.code)
                    Keys.onTabPressed: event => {
                        overlay.moveModalFocus(true)
                        event.accepted = true
                    }
                    Keys.onBacktabPressed: event => {
                        overlay.moveModalFocus(false)
                        event.accepted = true
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "详情是打开时的冻结快照，不会随后台进度改写。"
                color: Theme.faintText
                font.pixelSize: 9
            }
        }
    }
}
