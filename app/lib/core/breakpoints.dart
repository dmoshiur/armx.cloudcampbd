import 'package:flutter/widgets.dart';

/// compact(<600) / medium(600-1024) / expanded(>=1024), shared with the web app.
enum ArmxWindow { compact, medium, expanded }

class Breakpoints {
  static const double medium = 600;
  static const double expanded = 1024;

  static ArmxWindow of(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    if (width >= expanded) return ArmxWindow.expanded;
    if (width >= medium) return ArmxWindow.medium;
    return ArmxWindow.compact;
  }

  static bool isCompact(BuildContext context) => of(context) == ArmxWindow.compact;
}
