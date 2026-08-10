pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
import "components"

Item {
    id: page
    objectName: "masterDataPage"

    signal importRequested
    property var selectedSecurity: null
    property var selectedEntity: null
    property bool tagManagerOpen: false
    property bool classificationMemberOpen: false
    property bool watchlistMemberOpen: false
    property bool deleteConfirmOpen: false
    property bool refreshConfirmOpen: false
    property bool classificationUnbindConfirmOpen: false
    property var classificationUnbindImpact: ({})
    readonly property bool modalOverlayOpen:
        tagManagerOpen || classificationMemberOpen || watchlistMemberOpen
        || deleteConfirmOpen || refreshConfirmOpen
        || classificationUnbindConfirmOpen
    property var deleteImpact: ({})
    property string createNameError: ""

    function hasClassification(classificationId) {
        return Boolean(selectedSecurity && selectedSecurity.classifications)
            && selectedSecurity.classifications.some(
                item => item.id === classificationId)
    }

    function refreshSelectedSecurity() {
        if (!selectedSecurity) {
            return
        }
        // qmllint disable unqualified
        const selectedId = selectedSecurity.id
        selectedSecurity = masterDataBridge.securities.find(
            item => item.id === selectedId) || null
        selectedEntity = selectedSecurity
        // qmllint enable unqualified
    }

    function setClassification(classificationId, selected) {
        if (!selectedSecurity) {
            return
        }
        let ids = selectedSecurity.classifications.map(item => item.id)
        if (selected && !ids.includes(classificationId) && ids.length < 3) {
            ids.push(classificationId)
        } else if (!selected) {
            ids = ids.filter(item => item !== classificationId)
        }
        // qmllint disable unqualified
        if (masterDataBridge.set_security_classifications(
                selectedSecurity.id, ids)) {
            page.refreshSelectedSecurity()
        }
        // qmllint enable unqualified
    }

    function requestClassificationRemoval(security, classificationId) {
        if (!security) {
            return
        }
        // qmllint disable unqualified
        const impact = masterDataBridge
            .security_classification_removal_impact(
                security.id, classificationId)
        // qmllint enable unqualified
        if (!impact || !impact.securityId) {
            return
        }
        classificationUnbindImpact = impact
        classificationUnbindConfirmOpen = true
    }

    function snapshotText(key, fallback) {
        // qmllint disable unqualified
        const snapshot = masterDataBridge.security_snapshot
        if (!selectedSecurity
                || snapshot.securityId !== selectedSecurity.id) {
            return masterDataBridge.snapshot_running ? "正在获取…" : fallback
        }
        return snapshot[key] || fallback
        // qmllint enable unqualified
    }

    function visibleClassifications(query) {
        // qmllint disable unqualified
        const rows = masterDataBridge.classifications
        // qmllint enable unqualified
        const normalized = query.trim().toLowerCase()
        return rows.filter(item => {
            const label = item.displayName || item.name
            return !page.hasClassification(item.id)
                && (!normalized || label.toLowerCase().includes(normalized))
        })
    }

    function updateSelectedWatchlistBinding(securityId, bindingId) {
        const scrollPosition = entityMemberList.contentY
        // qmllint disable unqualified
        const updated = masterDataBridge.update_watchlist_member_binding(
            masterDataBridge.selected_watchlist_id,
            securityId,
            bindingId)
        // qmllint enable unqualified
        if (updated) {
            Qt.callLater(function() {
                const maximum = Math.max(0,
                    entityMemberList.contentHeight - entityMemberList.height)
                entityMemberList.contentY = Math.max(0,
                    Math.min(scrollPosition, maximum))
            })
        }
        return updated
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 66

            Column {
                spacing: 6
                Text {
                    // qmllint disable unqualified
                    text: shellBridge.page_title
                    // qmllint enable unqualified
                    color: Theme.text
                    font.pixelSize: 25
                    font.weight: Font.Bold
                }
                Text {
                    // qmllint disable unqualified
                    text: shellBridge.current_page === "securities"
                        ? "证券资料全局只保留一份；业务标签保持少而稳定。"
                        : (shellBridge.current_page === "classifications"
                            ? "行业与板块统一为一个全局业务标签维度。"
                            : "同一证券可进入多个股票池，每个池只选择一个参评标签。")
                    // qmllint enable unqualified
                    color: Theme.secondaryText
                    font.pixelSize: 12
                }
            }
            Item { Layout.fillWidth: true }
            RowLayout {
                // qmllint disable unqualified
                visible: shellBridge.current_page === "securities"
                // qmllint enable unqualified
                spacing: 8
                GlassButton {
                    objectName: "globalRefreshButton"
                    text: "更新全部"
                    implicitWidth: 104
                    // qmllint disable unqualified
                    enabled: !masterDataBridge.refresh_running
                    // qmllint enable unqualified
                    onClicked: page.refreshConfirmOpen = true
                }
                GlassButton {
                    text: "导入证券"
                    primary: true
                    implicitWidth: 104
                    // qmllint disable unqualified
                    enabled: !masterDataBridge.refresh_running
                    // qmllint enable unqualified
                    onClicked: page.importRequested()
                }
            }
        }

        Rectangle {
            objectName: "globalRefreshProgress"
            // qmllint disable unqualified
            visible: shellBridge.current_page === "securities"
                && (masterDataBridge.refresh_running
                    || masterDataBridge.refresh_status.length > 0)
            // qmllint enable unqualified
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            radius: 15
            color: Theme.field
            border.width: 1
            border.color: Theme.hairline

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 7
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        // qmllint disable unqualified
                        text: masterDataBridge.refresh_status
                        // qmllint enable unqualified
                        color: Theme.secondaryText
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                    Text {
                        // qmllint disable unqualified
                        text: Math.round(
                            refreshProgressBar.value * 100) + "%"
                        // qmllint enable unqualified
                        color: Theme.faintText
                        font.pixelSize: 10
                    }
                }
                ProgressBar {
                    id: refreshProgressBar
                    Layout.fillWidth: true
                    // qmllint disable unqualified
                    value: masterDataBridge.refresh_progress
                    // qmllint enable unqualified
                    Behavior on value {
                        NumberAnimation {
                            duration: 480
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
                            width: parent.width * Math.max(
                                0, Math.min(1,
                                    refreshProgressBar.visualPosition))
                            height: parent.height
                            radius: 4
                            color: Theme.accent
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14

            GlassPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        GlassTextInput {
                            id: quickInput
                            Layout.fillWidth: true
                            // qmllint disable unqualified
                            placeholderText: shellBridge.current_page === "securities"
                                ? "搜索代码或公司名称"
                                : (shellBridge.current_page === "classifications"
                                    ? "输入新标签名称"
                                    : "输入新股票池名称")
                            onTextChanged: {
                                page.createNameError = ""
                                if (shellBridge.current_page === "securities") {
                                    masterDataBridge.set_search(text)
                                }
                            }
                            // qmllint enable unqualified
                        }
                        GlassButton {
                            // qmllint disable unqualified
                            visible: shellBridge.current_page !== "securities"
                            text: shellBridge.current_page === "classifications"
                                ? "添加标签" : "新建股票池"
                            onClicked: {
                                const name = quickInput.text.trim()
                                if (!name) {
                                    page.createNameError =
                                        shellBridge.current_page === "watchlists"
                                        ? "请先输入股票池名称"
                                        : "请先输入标签名称"
                                    quickInput.forceActiveFocus()
                                    return
                                }
                                if (shellBridge.current_page === "classifications") {
                                    masterDataBridge.create_classification(
                                        name)
                                } else {
                                    const createdId =
                                        masterDataBridge.create_watchlist(name)
                                    if (!createdId) {
                                        page.createNameError =
                                            masterDataBridge.status
                                        return
                                    }
                                    selectedEntity =
                                        masterDataBridge.watchlists.find(
                                            item => item.id === createdId) || null
                                    watchlistNameInput.text = name
                                }
                                quickInput.clear()
                            }
                            // qmllint enable unqualified
                        }
                    }

                    Text {
                        visible: page.createNameError.length > 0
                        text: page.createNameError
                        color: Theme.danger
                        font.pixelSize: 11
                        Layout.fillWidth: true
                    }

                    ListView {
                        id: masterList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 8
                        // qmllint disable unqualified
                        model: shellBridge.current_page === "securities"
                            ? masterDataBridge.securities
                            : (shellBridge.current_page === "classifications"
                                ? masterDataBridge.classifications
                                : masterDataBridge.watchlists)
                        // qmllint enable unqualified

                        delegate: Rectangle {
                            id: masterRow
                            required property var modelData

                            width: ListView.view.width
                            // qmllint disable unqualified
                            height: shellBridge.current_page === "securities"
                                ? 76 : 56
                            // qmllint enable unqualified
                            radius: 15
                            color: {
                                const chosen = Boolean(page.selectedEntity
                                    && page.selectedEntity.id)
                                    && page.selectedEntity.id
                                        === masterRow.modelData.id
                                return chosen
                                    ? Theme.accentSoft
                                    : (rowMouse.containsMouse
                                        ? Theme.accentSoft : Theme.field)
                            }
                            border.width: 1
                            border.color: Theme.hairline

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14
                                spacing: 12

                                Text {
                                    // qmllint disable unqualified
                                    visible: shellBridge.current_page === "securities"
                                    // qmllint enable unqualified
                                    text: String(masterRow.modelData.rowNumber || "")
                                        .padStart(2, "0")
                                    color: Theme.faintText
                                    font.pixelSize: 11
                                    font.family: "Menlo"
                                    Layout.preferredWidth: 24
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 5
                                    Text {
                                        Layout.fillWidth: true
                                        // qmllint disable unqualified
                                        text: shellBridge.current_page === "securities"
                                            ? masterRow.modelData.displaySymbol
                                                + "  "
                                                + masterRow.modelData.name
                                            : masterRow.modelData.name
                                        // qmllint enable unqualified
                                        color: Theme.text
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }
                                    Row {
                                        spacing: 6
                                        // qmllint disable unqualified
                                        visible: shellBridge.current_page
                                            === "securities"
                                        // qmllint enable unqualified
                                        Repeater {
                                            model: masterRow.modelData.classifications
                                                || []
                                            delegate: Rectangle {
                                                required property var modelData
                                                height: 22
                                                width: listTagRow.implicitWidth + 14
                                                radius: 8
                                                color: Theme.accentSoft
                                                Row {
                                                    id: listTagRow
                                                    anchors.centerIn: parent
                                                    spacing: 4
                                                    TagIcon {
                                                        anchors.verticalCenter:
                                                            parent.verticalCenter
                                                    }
                                                    Text {
                                                        text: modelData.name
                                                        color: Theme.accent
                                                        font.pixelSize: 10
                                                    }
                                                }
                                            }
                                        }
                                        Text {
                                            visible: !masterRow.modelData.classifications
                                                || masterRow.modelData.classifications.length === 0
                                            text: "◇  待分类"
                                            color: Theme.faintText
                                            font.pixelSize: 10
                                        }
                                    }
                                    Text {
                                        // qmllint disable unqualified
                                        visible: shellBridge.current_page
                                            !== "securities"
                                        // qmllint enable unqualified
                                        text: masterRow.modelData.memberCount !== undefined
                                            ? masterRow.modelData.memberCount + " 位成员"
                                            : (masterRow.modelData.origin === "AI"
                                                ? "AI 创建" : "人工创建")
                                        color: Theme.secondaryText
                                        font.pixelSize: 10
                                    }
                                }
                                Rectangle {
                                    // qmllint disable unqualified
                                    visible: shellBridge.current_page
                                        === "securities"
                                        && masterRow.modelData.availabilityStatus
                                            !== "UNKNOWN"
                                    // qmllint enable unqualified
                                    Layout.preferredWidth: availabilityLabel
                                        .implicitWidth + 18
                                    Layout.preferredHeight: 26
                                    radius: 9
                                    // qmllint disable unqualified
                                    color: masterRow.modelData.availabilityStatus
                                        === "ACTIVE"
                                        ? Theme.successSoft : Theme.dangerSoft
                                    // qmllint enable unqualified
                                    Text {
                                        id: availabilityLabel
                                        anchors.centerIn: parent
                                        // qmllint disable unqualified
                                        text: masterRow.modelData
                                            .availabilityStatus === "ACTIVE"
                                            ? "有效"
                                            : (masterRow.modelData
                                                .availabilityStatus
                                                === "UNAVAILABLE"
                                                ? "资料不可用" : "检查失败")
                                        color: masterRow.modelData
                                            .availabilityStatus === "ACTIVE"
                                            ? Theme.success : Theme.danger
                                        // qmllint enable unqualified
                                        font.pixelSize: 10
                                    }
                                }
                            }

                            MouseArea {
                                id: rowMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: {
                                    // qmllint disable unqualified
                                    if (shellBridge.current_page === "securities") {
                                        page.selectedSecurity = modelData
                                        page.selectedEntity = modelData
                                        masterDataBridge.load_security_snapshot(
                                            modelData.id)
                                    } else if (shellBridge.current_page
                                            === "classifications") {
                                        page.selectedEntity = modelData
                                        masterDataBridge.select_classification(
                                            modelData.id)
                                    } else {
                                        page.selectedEntity = modelData
                                        masterDataBridge.select_watchlist(modelData.id)
                                        watchlistNameInput.text = modelData.name
                                    }
                                    // qmllint enable unqualified
                                }
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: masterList.count === 0
                            // qmllint disable unqualified
                            text: shellBridge.current_page === "securities"
                                ? "还没有证券\n点击右上角“导入证券”开始建立资料库"
                                : "暂时没有内容"
                            // qmllint enable unqualified
                            color: Theme.secondaryText
                            font.pixelSize: 12
                            horizontalAlignment: Text.AlignHCenter
                            lineHeight: 1.5
                        }
                    }
                }
            }

            GlassPanel {
                Layout.preferredWidth: 390
                Layout.fillHeight: true

                Item {
                    anchors.fill: parent
                    anchors.margins: 18

                    Column {
                        anchors.centerIn: parent
                        width: parent.width - 30
                        spacing: 8
                        // qmllint disable unqualified
                        visible: shellBridge.current_page === "securities"
                            && page.selectedSecurity === null
                        // qmllint enable unqualified
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "选择一只证券"
                            color: Theme.text
                            font.pixelSize: 16
                            font.weight: Font.DemiBold
                        }
                        Text {
                            width: parent.width
                            text: "这里会展示公司资料、实时行情摘要和已绑定的业务标签。"
                            color: Theme.secondaryText
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }

                    ScrollView {
                        anchors.fill: parent
                        clip: true
                        // qmllint disable unqualified
                        visible: shellBridge.current_page === "securities"
                            && page.selectedSecurity !== null
                        // qmllint enable unqualified

                        Column {
                            width: 348
                            spacing: 18

                            Column {
                                width: parent.width
                                spacing: 6
                                Text {
                                    text: page.selectedSecurity
                                        ? page.selectedSecurity.displaySymbol : ""
                                    color: Theme.text
                                    font.pixelSize: 24
                                    font.weight: Font.Bold
                                }
                                Text {
                                    width: parent.width
                                    text: page.selectedSecurity
                                        ? page.selectedSecurity.name : ""
                                    color: Theme.secondaryText
                                    font.pixelSize: 13
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: page.selectedSecurity
                                        ? [
                                            page.selectedSecurity.exchange,
                                            page.selectedSecurity.assetTypeText,
                                            page.selectedSecurity.currency
                                        ].filter(value => value).join(" · ")
                                        : ""
                                    color: Theme.faintText
                                    font.pixelSize: 10
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 10
                                Rectangle {
                                    width: (parent.width - 10) / 2
                                    height: 72
                                    radius: 14
                                    color: Theme.field
                                    border.width: 1
                                    border.color: Theme.hairline
                                    Column {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 7
                                        Text {
                                            text: "最新价"
                                            color: Theme.secondaryText
                                            font.pixelSize: 10
                                        }
                                        Text {
                                            text: page.snapshotText(
                                                "lastPrice",
                                                page.selectedSecurity
                                                    ? (page.selectedSecurity
                                                        .cachedLastPrice
                                                        || "暂不可用")
                                                    : "暂不可用")
                                            color: Theme.text
                                            font.pixelSize: 15
                                            font.weight: Font.DemiBold
                                        }
                                    }
                                }
                                Rectangle {
                                    width: (parent.width - 10) / 2
                                    height: 72
                                    radius: 14
                                    color: Theme.field
                                    border.width: 1
                                    border.color: Theme.hairline
                                    Column {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 7
                                        Text {
                                            text: "总市值"
                                            color: Theme.secondaryText
                                            font.pixelSize: 10
                                        }
                                        Text {
                                            text: page.snapshotText(
                                                "marketValue",
                                                page.selectedSecurity
                                                    ? (page.selectedSecurity
                                                        .cachedMarketValue
                                                        || "暂不可用")
                                                    : "暂不可用")
                                            color: Theme.text
                                            font.pixelSize: 15
                                            font.weight: Font.DemiBold
                                        }
                                    }
                                }
                            }

                            Column {
                                width: parent.width
                                spacing: 8
                                Text {
                                    text: "公司资料"
                                    color: Theme.text
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    width: parent.width
                                    text: page.selectedSecurity
                                        && page.selectedSecurity.description
                                        ? page.selectedSecurity.description
                                        : "供应商暂未提供公司简介。"
                                    color: Theme.secondaryText
                                    font.pixelSize: 11
                                    wrapMode: Text.WordWrap
                                    lineHeight: 1.35
                                }
                                Text {
                                    width: parent.width
                                    text: page.selectedSecurity
                                        ? [
                                            page.selectedSecurity.founded
                                                ? "成立 " + page.selectedSecurity.founded : "",
                                            page.selectedSecurity.employees
                                                ? "员工 " + page.selectedSecurity.employees : "",
                                            page.selectedSecurity.website
                                        ].filter(value => value).join("  ·  ")
                                        : ""
                                    visible: text.length > 0
                                    color: Theme.faintText
                                    font.pixelSize: 10
                                    wrapMode: Text.WrapAnywhere
                                }
                            }

                            Column {
                                width: parent.width
                                spacing: 10
                                Row {
                                    width: parent.width
                                    Text {
                                        text: "业务标签"
                                        color: Theme.text
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: page.selectedSecurity
                                            ? "  " + page.selectedSecurity
                                                .classifications.length + "/3"
                                            : ""
                                        color: Theme.faintText
                                        font.pixelSize: 10
                                    }
                                }
                                Flow {
                                    width: parent.width
                                    spacing: 7
                                    Repeater {
                                        model: page.selectedSecurity
                                            ? page.selectedSecurity.classifications : []
                                        delegate: Rectangle {
                                            required property var modelData
                                            height: 30
                                            width: boundTagRow.implicitWidth + 18
                                            radius: 10
                                            color: Theme.accentSoft
                                            Row {
                                                id: boundTagRow
                                                anchors.centerIn: parent
                                                spacing: 5
                                                TagIcon {
                                                    anchors.verticalCenter:
                                                        parent.verticalCenter
                                                }
                                                Text {
                                                    text: modelData.name
                                                    color: Theme.accent
                                                    font.pixelSize: 11
                                                }
                                            }
                                        }
                                    }
                                    Text {
                                        visible: Boolean(page.selectedSecurity
                                            && page.selectedSecurity.classifications)
                                            && page.selectedSecurity.classifications.length === 0
                                        text: "尚未分类"
                                        color: Theme.faintText
                                        font.pixelSize: 11
                                    }
                                }
                                GlassButton {
                                    text: "编辑业务标签"
                                    onClicked: page.tagManagerOpen = true
                                }
                            }

                            Rectangle {
                                width: parent.width
                                height: 1
                                color: Theme.hairline
                            }

                            GlassButton {
                                text: "删除该证券"
                                onClicked: {
                                    // qmllint disable unqualified
                                    page.deleteImpact =
                                        masterDataBridge.security_delete_impact(
                                            page.selectedSecurity.id)
                                    // qmllint enable unqualified
                                    page.deleteConfirmOpen = true
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        anchors.fill: parent
                        // qmllint disable unqualified
                        visible: shellBridge.current_page !== "securities"
                        // qmllint enable unqualified
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                // qmllint disable unqualified
                                text: shellBridge.current_page === "watchlists"
                                    ? "当前股票池" : "标签下的证券"
                                // qmllint enable unqualified
                                color: Theme.text
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            Item { Layout.fillWidth: true }
                            GlassButton {
                                // qmllint disable unqualified
                                visible: Boolean(page.selectedEntity)
                                    && (shellBridge.current_page
                                        === "classifications"
                                        || shellBridge.current_page
                                            === "watchlists")
                                // qmllint enable unqualified
                                // qmllint disable unqualified
                                text: shellBridge.current_page
                                    === "watchlists"
                                    ? "添加证券" : "批量添加证券"
                                // qmllint enable unqualified
                                primary: true
                                onClicked: {
                                    // qmllint disable unqualified
                                    if (shellBridge.current_page
                                            === "watchlists") {
                                        masterDataBridge.select_watchlist(
                                            page.selectedEntity.id)
                                        page.watchlistMemberOpen = true
                                    } else {
                                        masterDataBridge.select_classification(
                                            page.selectedEntity.id)
                                        page.classificationMemberOpen = true
                                    }
                                    // qmllint enable unqualified
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            // qmllint disable unqualified
                            visible: shellBridge.current_page === "watchlists"
                                && Boolean(page.selectedEntity)
                            // qmllint enable unqualified
                            spacing: 7
                            GlassTextInput {
                                id: watchlistNameInput
                                objectName: "watchlistNameInput"
                                Layout.fillWidth: true
                                placeholderText: "股票池名称"
                            }
                            GlassButton {
                                text: "重命名"
                                enabled: watchlistNameInput.text.trim().length > 0
                                onClicked: {
                                    // qmllint disable unqualified
                                    if (masterDataBridge.rename_watchlist(
                                            page.selectedEntity.id,
                                            watchlistNameInput.text)) {
                                        page.selectedEntity =
                                            masterDataBridge.watchlists.find(
                                                item => item.id
                                                    === page.selectedEntity.id)
                                        watchlistNameInput.text =
                                            page.selectedEntity.name
                                    }
                                    // qmllint enable unqualified
                                }
                            }
                            GlassButton {
                                text: "删除"
                                onClicked: {
                                    // qmllint disable unqualified
                                    if (masterDataBridge.delete_watchlist(
                                            page.selectedEntity.id)) {
                                        page.selectedEntity = null
                                        watchlistNameInput.clear()
                                    }
                                    // qmllint enable unqualified
                                }
                            }
                        }

                        ListView {
                            id: entityMemberList
                            objectName: "watchlistMemberList"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 6
                            // qmllint disable unqualified
                            model: shellBridge.current_page === "watchlists"
                                ? masterDataBridge.selected_watchlist_members
                                : masterDataBridge.classification_members
                            // qmllint enable unqualified
                            delegate: Rectangle {
                                id: poolMember
                                required property var modelData
                                width: ListView.view.width
                                // qmllint disable unqualified
                                height: shellBridge.current_page === "watchlists"
                                    ? 58 : 46
                                // qmllint enable unqualified
                                radius: 12
                                color: Theme.field
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 8
                                    ColumnLayout {
                                        // qmllint disable unqualified
                                        visible: shellBridge.current_page
                                            === "watchlists"
                                        // qmllint enable unqualified
                                        Layout.fillWidth: true
                                        spacing: 3
                                        Text {
                                            text: poolMember.modelData.displaySymbol
                                                + "  "
                                                + poolMember.modelData.name
                                            color: Theme.text
                                            font.pixelSize: 11
                                            font.weight: Font.DemiBold
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            text: "当前参评标签"
                                            color: Theme.faintText
                                            font.pixelSize: 9
                                        }
                                    }
                                    Text {
                                        // qmllint disable unqualified
                                        visible: shellBridge.current_page
                                            === "classifications"
                                        // qmllint enable unqualified
                                        text: poolMember.modelData.displaySymbol
                                            + "  " + poolMember.modelData.name
                                        color: Theme.text
                                        font.pixelSize: 11
                                        Layout.fillWidth: true
                                    }
                                    GlassField {
                                        // qmllint disable unqualified
                                        visible: shellBridge.current_page
                                            === "watchlists"
                                        // qmllint enable unqualified
                                        Layout.preferredWidth: 142
                                        model: poolMember.modelData.bindings || []
                                        textRole: "name"
                                        valueRole: "bindingId"
                                        valueText: poolMember.modelData
                                            .classification || ""
                                        onActivated: {
                                            page.updateSelectedWatchlistBinding(
                                                poolMember.modelData.securityId,
                                                currentValue)
                                        }
                                    }
                                    GlassButton {
                                        // qmllint disable unqualified
                                        visible: shellBridge.current_page
                                            === "watchlists"
                                        // qmllint enable unqualified
                                        text: "移除"
                                        onClicked: {
                                            // qmllint disable unqualified
                                            masterDataBridge.remove_watchlist_member(
                                                masterDataBridge.selected_watchlist_id,
                                                poolMember.modelData.securityId)
                                            // qmllint enable unqualified
                                        }
                                    }
                                    GlassButton {
                                        // qmllint disable unqualified
                                        visible: shellBridge.current_page
                                            === "classifications"
                                        // qmllint enable unqualified
                                        text: "移除"
                                        onClicked: page
                                            .requestClassificationRemoval(
                                                poolMember.modelData,
                                                page.selectedEntity.id)
                                    }
                                }
                            }

                            Text {
                                anchors.centerIn: parent
                                visible: entityMemberList.count === 0
                                // qmllint disable unqualified
                                text: !page.selectedEntity
                                    ? (shellBridge.current_page
                                        === "watchlists"
                                        ? "选择一个股票池查看成员"
                                        : "选择一个标签查看关联证券")
                                    : (shellBridge.current_page
                                        === "classifications"
                                        ? "该标签下还没有证券"
                                        : "当前股票池还没有证券")
                                // qmllint enable unqualified
                                color: Theme.faintText
                                font.pixelSize: 11
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            // qmllint disable unqualified
                            visible: shellBridge.current_page
                                === "classifications"
                                && Boolean(page.selectedEntity)
                            // qmllint enable unqualified
                            spacing: 7
                            GlassTextInput {
                                id: renameInput
                                Layout.fillWidth: true
                                placeholderText: page.selectedEntity
                                    ? page.selectedEntity.name : "新名称"
                            }
                            RowLayout {
                                GlassButton {
                                    text: "重命名"
                                    enabled: renameInput.text.trim().length > 0
                                    onClicked: {
                                        // qmllint disable unqualified
                                        const ok = shellBridge.current_page
                                            === "classifications"
                                            ? masterDataBridge.rename_classification(
                                                page.selectedEntity.id,
                                                renameInput.text)
                                            : masterDataBridge.rename_watchlist(
                                                page.selectedEntity.id,
                                                renameInput.text)
                                        // qmllint enable unqualified
                                        if (ok) {
                                            renameInput.clear()
                                            page.selectedEntity = null
                                        }
                                    }
                                }
                                GlassButton {
                                    text: "删除"
                                    onClicked: {
                                        // qmllint disable unqualified
                                        const ok = shellBridge.current_page
                                            === "classifications"
                                            ? masterDataBridge.delete_classification(
                                                page.selectedEntity.id)
                                            : masterDataBridge.delete_watchlist(
                                                page.selectedEntity.id)
                                        // qmllint enable unqualified
                                        if (ok) {
                                            page.selectedEntity = null
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            // qmllint disable unqualified
                            text: masterDataBridge.status
                            // qmllint enable unqualified
                            color: Theme.secondaryText
                            font.pixelSize: 10
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }

    ClassificationMemberOverlay {
        anchors.fill: parent
        visible: page.classificationMemberOpen
        classification: page.selectedEntity
        // qmllint disable unqualified
        candidates: masterDataBridge.classification_candidates
        batchResult: masterDataBridge.classification_batch_result
        // qmllint enable unqualified
        onCloseRequested: page.classificationMemberOpen = false
        onSubmitRequested: securityIds => {
            // qmllint disable unqualified
            masterDataBridge.add_classification_members(
                page.selectedEntity.id, securityIds)
            // qmllint enable unqualified
        }
    }

    WatchlistMemberOverlay {
        anchors.fill: parent
        visible: page.watchlistMemberOpen
        watchlist: page.selectedEntity
        // qmllint disable unqualified
        candidates: masterDataBridge.watchlist_candidates
        // qmllint enable unqualified
        onCloseRequested: page.watchlistMemberOpen = false
    }

    Rectangle {
        id: tagOverlay
        objectName: "tagManagerOverlay"
        anchors.fill: parent
        z: 50
        visible: page.tagManagerOpen
        color: Theme.modalScrim
        MouseArea { anchors.fill: parent }

        GlassPanel {
            width: 540
            height: 540
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
                            text: "管理业务标签"
                            color: Theme.text
                            font.pixelSize: 20
                            font.weight: Font.Bold
                        }
                        Text {
                            text: page.selectedSecurity
                                ? page.selectedSecurity.displaySymbol
                                    + " · 已选 "
                                    + page.selectedSecurity.classifications.length
                                    + "/3"
                                : ""
                            color: Theme.secondaryText
                            font.pixelSize: 11
                        }
                    }
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "完成"
                        onClicked: page.tagManagerOpen = false
                    }
                }

                Text {
                    text: "已选标签"
                    color: Theme.text
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 7
                    Repeater {
                        model: page.selectedSecurity
                            ? page.selectedSecurity.classifications : []
                        delegate: Rectangle {
                            required property var modelData
                            width: selectedTagRow.implicitWidth + 20
                            height: 36
                            radius: 12
                            color: Theme.field
                            border.width: 1
                            border.color: Theme.hairline
                            Row {
                                id: selectedTagRow
                                anchors.centerIn: parent
                                spacing: 6
                                TagIcon {
                                    anchors.verticalCenter:
                                        parent.verticalCenter
                                }
                                Text {
                                    text: modelData.name
                                    color: Theme.text
                                    font.pixelSize: 12
                                }
                                Text {
                                    text: "×"
                                    color: Theme.secondaryText
                                    font.pixelSize: 12
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: page.requestClassificationRemoval(
                                    page.selectedSecurity, modelData.id)
                            }
                        }
                    }
                    Text {
                        visible: Boolean(page.selectedSecurity
                            && page.selectedSecurity.classifications)
                            && page.selectedSecurity.classifications.length === 0
                        text: "暂无，最多可添加三个。"
                        color: Theme.faintText
                        font.pixelSize: 11
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: Theme.hairline
                }
                Text {
                    text: "从全局标签池添加"
                    color: Theme.text
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
                GlassTextInput {
                    id: tagSearch
                    Layout.fillWidth: true
                    placeholderText: "搜索中文业务标签"
                }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 7
                    clip: true
                    model: page.visibleClassifications(tagSearch.text)
                    delegate: Rectangle {
                        id: candidateTag
                        required property var modelData
                        width: ListView.view.width
                        height: 44
                        radius: 12
                        color: Theme.field
                        border.width: 1
                        border.color: Theme.hairline
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 8
                            Row {
                                Layout.fillWidth: true
                                spacing: 6
                                TagIcon {
                                    anchors.verticalCenter:
                                        parent.verticalCenter
                                }
                                Text {
                                    text: candidateTag.modelData.displayName
                                        || candidateTag.modelData.name
                                    color: Theme.text
                                    font.pixelSize: 11
                                }
                            }
                            GlassButton {
                                text: "添加"
                                enabled: Boolean(page.selectedSecurity
                                    && page.selectedSecurity.classifications)
                                    && page.selectedSecurity.classifications
                                        .length < 3
                                onClicked: page.setClassification(
                                    candidateTag.modelData.id, true)
                            }
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: "没有合适标签时，请先到“全局标签”创建一个较粗的中文业务分类。"
                    color: Theme.faintText
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    Rectangle {
        id: classificationUnbindConfirmOverlay
        objectName: "classificationUnbindConfirmOverlay"
        anchors.fill: parent
        z: 60
        visible: page.classificationUnbindConfirmOpen
        color: Theme.modalScrim
        MouseArea { anchors.fill: parent }

        GlassPanel {
            width: 480
            implicitHeight: unbindConfirmColumn.implicitHeight + 48
            anchors.centerIn: parent
            color: Theme.dark ? "#F021242A" : "#FFF8F7F4"

            ColumnLayout {
                id: unbindConfirmColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 24
                spacing: 13

                Text {
                    text: "移除证券标签？"
                    color: Theme.text
                    font.pixelSize: 20
                    font.weight: Font.Bold
                }
                Text {
                    Layout.fillWidth: true
                    text: page.classificationUnbindImpact.symbol
                        + "  " + page.classificationUnbindImpact.name
                        + "\n将移除「"
                        + page.classificationUnbindImpact.classificationName
                        + "」标签。"
                    color: Theme.text
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: impactText.implicitHeight + 24
                    radius: 13
                    color: Theme.field
                    border.width: 1
                    border.color: Theme.hairline
                    Text {
                        id: impactText
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 12
                        text: {
                            const count = page.classificationUnbindImpact
                                .watchlistCount || 0
                            if (count === 0) {
                                return "没有股票池使用这个标签，只解除全局绑定。"
                            }
                            const pools = (page.classificationUnbindImpact
                                .watchlistNames || []).join("、")
                            const replacement = page
                                .classificationUnbindImpact.replacementName || ""
                            return "当前参与 " + count + " 个股票池的后续计算"
                                + (pools ? "（" + pools + "）" : "") + "。\n"
                                + (replacement
                                    ? "移除后自动改用「" + replacement + "」参评。"
                                    : "移除后该证券会从这些股票池中移出。")
                        }
                        color: Theme.secondaryText
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: "已保存的历史结果保持不变；后续运行按新绑定计算。"
                    color: Theme.faintText
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "取消"
                        onClicked: page.classificationUnbindConfirmOpen = false
                    }
                    GlassButton {
                        text: "确认移除"
                        primary: true
                        onClicked: {
                            // qmllint disable unqualified
                            const ok = masterDataBridge
                                .remove_security_classification(
                                    page.classificationUnbindImpact.securityId,
                                    page.classificationUnbindImpact
                                        .classificationId)
                            // qmllint enable unqualified
                            if (ok) {
                                page.classificationUnbindConfirmOpen = false
                                page.refreshSelectedSecurity()
                            }
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        objectName: "globalRefreshConfirmOverlay"
        anchors.fill: parent
        z: 60
        visible: page.refreshConfirmOpen
        color: Theme.modalScrim
        MouseArea { anchors.fill: parent }

        GlassPanel {
            width: 470
            height: 312
            anchors.centerIn: parent
            color: Theme.dark ? "#F021242A" : "#FFF8F7F4"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 26
                spacing: 13
                Text {
                    text: "更新全部证券资料？"
                    color: Theme.text
                    font.pixelSize: 20
                    font.weight: Font.Bold
                }
                Text {
                    Layout.fillWidth: true
                    // qmllint disable unqualified
                    text: "将重新检查 "
                        + masterDataBridge.securities.length
                        + " 只证券的基础资料、最新价、总市值和可用状态。"
                    // qmllint enable unqualified
                    color: Theme.text
                    font.pixelSize: 13
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    text: "证券不可用时只会标记状态，不会自动删除股票池成员或历史结果；"
                        + "已有业务标签也不会被覆盖。过程在后台执行，可以继续查看当前页面。"
                    color: Theme.secondaryText
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    lineHeight: 1.35
                }
                Item { Layout.fillHeight: true }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "取消"
                        onClicked: page.refreshConfirmOpen = false
                    }
                    GlassButton {
                        objectName: "globalRefreshConfirmButton"
                        text: "确认开始更新"
                        primary: true
                        // qmllint disable unqualified
                        enabled: !masterDataBridge.refresh_running
                            && masterDataBridge.securities.length > 0
                        // qmllint enable unqualified
                        onClicked: {
                            // qmllint disable unqualified
                            if (masterDataBridge.refresh_securities()) {
                                page.refreshConfirmOpen = false
                            }
                            // qmllint enable unqualified
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        objectName: "deleteConfirmOverlay"
        anchors.fill: parent
        z: 60
        visible: page.deleteConfirmOpen
        color: Theme.modalScrim
        MouseArea { anchors.fill: parent }

        GlassPanel {
            width: 440
            height: 278
            anchors.centerIn: parent
            color: Theme.dark ? "#F021242A" : "#FFF8F7F4"
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 26
                spacing: 13
                Text {
                    text: "删除证券？"
                    color: Theme.text
                    font.pixelSize: 20
                    font.weight: Font.Bold
                }
                Text {
                    Layout.fillWidth: true
                    text: (page.deleteImpact.symbol || "")
                        + "  " + (page.deleteImpact.name || "")
                    color: Theme.text
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: "该证券会同时从 "
                        + String(page.deleteImpact.watchlistCount || 0)
                        + " 个股票池移除。全局标签池和历史计算结果不会被删除。"
                    color: Theme.secondaryText
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    lineHeight: 1.35
                }
                Item { Layout.fillHeight: true }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "取消"
                        onClicked: page.deleteConfirmOpen = false
                    }
                    GlassButton {
                        text: "确认删除"
                        primary: true
                        onClicked: {
                            // qmllint disable unqualified
                            if (page.selectedSecurity
                                    && masterDataBridge.delete_security(
                                        page.selectedSecurity.id)) {
                                // qmllint enable unqualified
                                page.selectedSecurity = null
                                page.selectedEntity = null
                            }
                            page.deleteConfirmOpen = false
                        }
                    }
                }
            }
        }
    }
}
