pragma ComponentBehavior: Bound
import QtQuick
import ".."

ListView {
    id: table

    property int rowHeight: 38

    clip: true
    spacing: 0

    delegate: Rectangle {
        required property int index
        required property var modelData

        width: table.width
        height: table.rowHeight
        color: index % 2
            ? (Theme.dark ? "#0DFFFFFF" : "#0A5369A8")
            : "transparent"
    }
}
