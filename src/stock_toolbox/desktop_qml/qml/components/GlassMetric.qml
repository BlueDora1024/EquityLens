import QtQuick
import ".."

GlassPanel {
    id: metric

    property string label: ""
    property string value: ""
    property bool compact: false

    implicitHeight: compact ? 68 : 84

    Column {
        anchors.fill: parent
        anchors.margins: metric.compact ? 10 : 16
        spacing: metric.compact ? 4 : 8

        Text {
            text: metric.label
            color: Theme.secondaryText
            font.pixelSize: metric.compact ? 10 : 11
        }

        Text {
            text: metric.value
            color: Theme.text
            font.pixelSize: metric.compact ? 18 : 20
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            width: parent.width
        }
    }
}
