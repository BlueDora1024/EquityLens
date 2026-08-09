pragma ComponentBehavior: Bound
import QtQuick
import ".."

Item {
    id: root

    property var stages: []
    property int activeIndex: -1
    property real progress: 0
    readonly property int stageCount: stages.length

    implicitHeight: 38

    Row {
        anchors.fill: parent
        spacing: 7

        Repeater {
            model: root.stages

            Rectangle {
                id: stageCell

                required property int index
                required property string modelData

                width: (root.width - 7 * (root.stageCount - 1)) / root.stageCount
                height: 36
                radius: 12
                color: index <= root.activeIndex ? Theme.accentSoft : Theme.field
                border.width: 1
                border.color: index === root.activeIndex ? Theme.accent : Theme.hairline

                Text {
                    anchors.centerIn: parent
                    text: (stageCell.index + 1) + "　" + stageCell.modelData
                    color: Theme.text
                    font.pixelSize: 11
                }
            }
        }
    }
}
