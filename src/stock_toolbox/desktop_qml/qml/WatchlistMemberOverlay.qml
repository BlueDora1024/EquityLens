pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "."
import "components"

Item {
    id: root
    objectName: "watchlistMemberOverlay"
    z: 55

    property var watchlist: null
    property var candidates: []
    property var candidateSnapshot: []
    property var selectedIds: []
    property var selections: []
    property int step: 1
    property int addedCount: 0
    property string submitError: ""

    signal closeRequested

    function filteredCandidates() {
        const normalized = searchInput.text.trim().toLowerCase()
        if (!normalized) {
            return candidateSnapshot
        }
        return candidateSnapshot.filter(item =>
            item.displaySymbol.toLowerCase().includes(normalized)
                || item.name.toLowerCase().includes(normalized))
    }

    function selectableVisibleIds(): var {
        return filteredCandidates()
            .filter(item => item.classifications.length > 0)
            .map(item => item.id)
    }

    function allVisibleSelected(): bool {
        const visibleIds = selectableVisibleIds()
        return visibleIds.length > 0
            && visibleIds.every(id => selectedIds.includes(id))
    }

    function toggleAllVisible(): void {
        const visibleIds = selectableVisibleIds()
        if (allVisibleSelected()) {
            selectedIds = selectedIds.filter(
                id => !visibleIds.includes(id))
            return
        }
        selectedIds = Array.from(new Set(selectedIds.concat(visibleIds)))
    }

    function toggleSecurity(securityId) {
        const candidate = candidateSnapshot.find(
            item => item.id === securityId)
        if (!candidate || !candidate.classifications.length) {
            return
        }
        const next = selectedIds.slice()
        const index = next.indexOf(securityId)
        if (index >= 0) {
            next.splice(index, 1)
        } else {
            next.push(securityId)
        }
        selectedIds = next
    }

    function prepareSelections() {
        selections = selectedIds.map(securityId => {
            const security = candidateSnapshot.find(
                item => item.id === securityId)
            return {
                securityId: security.id,
                displaySymbol: security.displaySymbol,
                name: security.name,
                bindings: security.classifications,
                bindingId: security.classifications[0].bindingId
            }
        })
        step = 2
    }

    function changeBinding(securityId, bindingId) {
        const selection = selections.find(
            item => item.securityId === securityId)
        if (selection) {
            selection.bindingId = bindingId
        }
    }

    function bindingName(selection) {
        const binding = selection.bindings.find(
            item => item.bindingId === selection.bindingId)
        return binding ? binding.name : "选择参评标签"
    }

    function submit() {
        // qmllint disable unqualified
        const result = masterDataBridge.add_watchlist_members_batch(
            watchlist.id,
            selections.map(item => ({
                securityId: item.securityId,
                bindingId: item.bindingId
            })))
        // qmllint enable unqualified
        addedCount = Number(result.added || 0)
        if (addedCount <= 0) {
            // qmllint disable unqualified
            submitError = masterDataBridge.status || "添加失败，请重试。"
            // qmllint enable unqualified
            return
        }
        submitError = ""
        step = 3
    }

    onVisibleChanged: {
        if (visible) {
            candidateSnapshot = candidates ? candidates.slice() : []
            selectedIds = []
            selections = []
            addedCount = 0
            submitError = ""
            step = 1
            searchInput.clear()
        }
    }

    onCandidatesChanged: {
        if (visible && selectedIds.length === 0) {
            candidateSnapshot = candidates ? candidates.slice() : []
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
                        text: root.step === 1
                            ? "选择证券"
                            : (root.step === 2
                                ? "调整参评标签" : "添加完成")
                        color: Theme.text
                        font.pixelSize: 20
                        font.weight: Font.Bold
                    }
                    Text {
                        text: root.watchlist
                            ? "添加到「" + root.watchlist.name + "」"
                            : ""
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                }
                Item { Layout.fillWidth: true }
                Text {
                    visible: root.step < 3
                    text: root.step + " / 2"
                    color: Theme.faintText
                    font.pixelSize: 10
                }
                GlassButton {
                    text: "关闭"
                    onClicked: root.closeRequested()
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.step === 1
                spacing: 12

                GlassTextInput {
                    id: searchInput
                    Layout.fillWidth: true
                    placeholderText: "搜索代码或公司名称"
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "未加入当前股票池"
                        color: Theme.text
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        objectName: "watchlistSelectAllButton"
                        text: root.allVisibleSelected()
                            ? "取消全选" : "全选当前结果"
                        enabled: root.selectableVisibleIds().length > 0
                        onClicked: root.toggleAllVisible()
                    }
                    Text {
                        text: "待添加 " + root.selectedIds.length + " 只"
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
                        readonly property bool available:
                            modelData.classifications.length > 0

                        width: ListView.view.width
                        height: 58
                        radius: 14
                        color: selected ? Theme.accentSoft : Theme.field
                        border.width: 1
                        border.color: selected
                            ? Theme.accent : Theme.hairline
                        opacity: available ? 1 : 0.48

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
                                    Layout.fillWidth: true
                                    text: candidateRow.modelData.displaySymbol
                                        + "  " + candidateRow.modelData.name
                                    color: Theme.text
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: candidateRow.available
                                        ? candidateRow.modelData.classifications
                                            .length + " 个可选标签"
                                        : "尚无业务标签，暂时不能加入股票池"
                                    color: Theme.faintText
                                    font.pixelSize: 10
                                }
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            enabled: candidateRow.available
                            onClicked: root.toggleSecurity(
                                candidateRow.modelData.id)
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: candidateList.count === 0
                        text: searchInput.text.trim()
                            ? "没有匹配的证券"
                            : "证券库中的证券都已加入当前股票池"
                        color: Theme.faintText
                        font.pixelSize: 11
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: "这里只是选择；点击“下一步”确认参评标签后，才会写入股票池。"
                        color: Theme.faintText
                        font.pixelSize: 10
                    }
                    GlassButton {
                        text: "取消"
                        onClicked: root.closeRequested()
                    }
                    GlassButton {
                        text: "下一步"
                        primary: true
                        enabled: root.selectedIds.length > 0
                        onClicked: root.prepareSelections()
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: root.step === 2
                spacing: 12

                Text {
                    Layout.fillWidth: true
                    text: "每只证券默认选择第一项；可在提交前逐只下拉调整。"
                    color: Theme.secondaryText
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    visible: root.submitError.length > 0
                    text: root.submitError
                    color: Theme.danger
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 8
                    clip: true
                    model: root.selections
                    delegate: Rectangle {
                        id: selectionRow
                        required property var modelData
                        width: ListView.view.width
                        height: 62
                        radius: 14
                        color: Theme.field
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 13
                            anchors.rightMargin: 13
                            spacing: 12
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Text {
                                    Layout.fillWidth: true
                                    text: selectionRow.modelData.displaySymbol
                                        + "  " + selectionRow.modelData.name
                                    color: Theme.text
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: "本池参评标签"
                                    color: Theme.faintText
                                    font.pixelSize: 9
                                }
                            }
                            GlassField {
                                Layout.preferredWidth: 190
                                model: selectionRow.modelData.bindings
                                textRole: "name"
                                valueRole: "bindingId"
                                valueText: root.bindingName(
                                    selectionRow.modelData)
                                onActivated: root.changeBinding(
                                    selectionRow.modelData.securityId,
                                    currentValue)
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    GlassButton {
                        text: "上一步"
                        onClicked: root.step = 1
                    }
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "确认添加 " + root.selections.length + " 只证券"
                        primary: true
                        onClicked: root.submit()
                    }
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.minimumWidth: Math.min(672, root.width - 84)
                Layout.preferredWidth: Math.min(672, root.width - 84)
                Layout.maximumWidth: Math.min(672, root.width - 84)
                Layout.fillHeight: true
                visible: root.step === 3

                Column {
                    width: parent.width
                    anchors.centerIn: parent
                    spacing: 14
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 66
                        height: 66
                        radius: 22
                        color: Theme.successSoft
                        Text {
                            anchors.centerIn: parent
                            text: "✓"
                            color: Theme.success
                            font.pixelSize: 28
                            font.weight: Font.Bold
                        }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "成功添加 " + root.addedCount + " 只证券"
                        color: Theme.text
                        font.pixelSize: 18
                        font.weight: Font.Bold
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "参评标签已按你的选择保存到当前股票池。"
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                    GlassButton {
                        objectName: "watchlistCompletionButton"
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 160
                        text: "完成"
                        primary: true
                        onClicked: root.closeRequested()
                    }
                }
            }
        }
    }
}
