pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import ".."

ComboBox {
    id: control

    property string valueText: ""
    property string trailingText: "⌄"
    property bool loading: false
    property bool loaded: true
    property string emptyText: "暂无可选项"
    signal opening

    implicitWidth: 180
    implicitHeight: Theme.controlHeight
    hoverEnabled: true
    leftPadding: 13
    rightPadding: 12
    indicator: null

    contentItem: Row {
        width: control.availableWidth
        height: control.availableHeight
        spacing: 8

        Text {
            width: parent.width - trailing.width - parent.spacing
            height: parent.height
            text: control.valueText
            color: Theme.text
            font.pixelSize: 13
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }

        Item {
            id: trailing
            height: parent.height
            width: 20
            BusyIndicator {
                anchors.centerIn: parent
                width: 18
                height: 18
                running: control.loading
                visible: control.loading
            }
            Text {
                anchors.centerIn: parent
                visible: !control.loading
                text: control.trailingText
                color: Theme.secondaryText
                font.pixelSize: 12
            }
        }
    }

    onPressedChanged: {
        if (pressed) {
            control.opening()
        }
    }

    delegate: ItemDelegate {
        id: delegateItem

        required property int index

        width: control.width
        text: control.textAt(index)
        highlighted: control.highlightedIndex === index

        contentItem: Text {
            text: delegateItem.text
            color: Theme.text
            font.pixelSize: 13
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 9
            color: delegateItem.highlighted ? Theme.accentSoft : "transparent"
        }
    }

    popup: Popup {
        y: control.height + 5
        width: control.width
        implicitHeight: control.count === 0
            ? 78 : Math.min(contentItem.implicitHeight + 12, 240)
        padding: 6

        contentItem: Item {
            implicitHeight: listView.visible ? listView.contentHeight : 66

            ListView {
                id: listView
                anchors.fill: parent
                clip: true
                visible: control.count > 0
                model: control.popup.visible ? control.delegateModel : null
                currentIndex: control.highlightedIndex
            }
            BusyIndicator {
                anchors.centerIn: parent
                width: 24
                height: 24
                running: control.loading
                visible: control.loading && control.count === 0
            }
            Text {
                anchors.centerIn: parent
                visible: !control.loading && control.count === 0
                text: control.loaded ? control.emptyText : "正在读取…"
                color: Theme.secondaryText
                font.pixelSize: 11
            }
        }

        background: Rectangle {
            radius: Theme.controlRadius
            color: Theme.dark ? "#F232353C" : "#FFF7F6F3"
            border.width: 1
            border.color: Theme.hairline
        }
    }

    background: Rectangle {
        radius: Theme.controlRadius
        color: control.hovered ? Theme.accentSoft : Theme.field
        border.width: 1
        border.color: Theme.hairline
    }
}
