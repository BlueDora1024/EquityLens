pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Item {
    id: root
    property var model: []
    property string valueText: "选择"
    property bool loading: false
    property string emptyText: "暂无可选项"
    signal selected(string value)
    signal opening()

    implicitHeight: Theme.controlHeight

    function filteredRows(query): var {
        const needle = String(query || "").trim().toLowerCase()
        if (!needle) return root.model || []
        const rows = []
        for (let index = 0; index < root.model.length; ++index) {
            const row = root.model[index]
            const haystack = (String(row.name || "") + " "
                + String(row.symbol || "")).toLowerCase()
            if (haystack.indexOf(needle) >= 0) rows.push(row)
        }
        return rows
    }

    GlassButton {
        anchors.fill: parent
        text: root.loading ? "正在读取证券…" : root.valueText + "  ⌄"
        onClicked: {
            root.opening()
            picker.open()
            search.forceActiveFocus()
        }
    }

    Popup {
        id: picker
        y: root.height + 6
        width: root.width
        height: 310
        padding: 8
        modal: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: search.clear()

        background: Rectangle {
            radius: 16
            color: Theme.dark ? "#FF24272E" : "#FFF8F7F4"
            border.width: 1
            border.color: Theme.hairline
        }

        contentItem: ColumnLayout {
            spacing: 8
            GlassTextInput {
                id: search
                Layout.fillWidth: true
                placeholderText: "搜索代码或公司名称"
            }
            Text {
                Layout.fillWidth: true
                text: "输入代码可直接定位；仅展示全局证券库中的有效证券"
                color: Theme.faintText
                font.pixelSize: 9
                elide: Text.ElideRight
            }
            ListView {
                id: resultList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 5
                model: root.filteredRows(search.text)
                delegate: Rectangle {
                    id: row
                    required property var modelData
                    width: ListView.view.width
                    height: 42
                    radius: 10
                    color: rowMouse.containsMouse ? Theme.accentSoft : Theme.field
                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        text: row.modelData.name
                        color: Theme.text
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.selected(String(row.modelData.id))
                            picker.close()
                        }
                    }
                }
            }
            Text {
                visible: resultList.count === 0 && !root.loading
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: search.text ? "没有匹配证券" : root.emptyText
                color: Theme.secondaryText
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
}
