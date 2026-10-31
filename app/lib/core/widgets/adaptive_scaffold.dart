import 'package:flutter/material.dart';

import '../breakpoints.dart';
import '../theme.dart';

class NavItem {
  const NavItem({required this.label, required this.icon, required this.builder});
  final String label;
  final IconData icon;
  final WidgetBuilder builder;
}

/// bottom navigation (compact) -> rail (medium) -> sidebar (expanded).
class AdaptiveScaffold extends StatefulWidget {
  const AdaptiveScaffold({
    super.key,
    required this.items,
    required this.title,
    this.actions = const [],
    this.initialIndex = 0,
  });

  final List<NavItem> items;
  final String title;
  final List<Widget> actions;
  final int initialIndex;

  @override
  State<AdaptiveScaffold> createState() => _AdaptiveScaffoldState();
}

class _AdaptiveScaffoldState extends State<AdaptiveScaffold> {
  late int _index = widget.initialIndex;

  void _select(int index) => setState(() => _index = index);

  @override
  Widget build(BuildContext context) {
    final size = Breakpoints.of(context);
    final body = widget.items[_index].builder(context);

    final content = Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: ArmxTheme.contentMaxWidth),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          child: body,
        ),
      ),
    );

    if (size == ArmxWindow.compact) {
      return Scaffold(
        appBar: AppBar(title: Text(widget.items[_index].label), actions: widget.actions),
        body: content,
        bottomNavigationBar: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: _select,
          destinations: widget.items
              .map((item) => NavigationDestination(icon: Icon(item.icon), label: item.label))
              .toList(),
        ),
      );
    }

    if (size == ArmxWindow.medium) {
      return Scaffold(
        appBar: AppBar(title: Text(widget.items[_index].label), actions: widget.actions),
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: _index,
              onDestinationSelected: _select,
              labelType: NavigationRailLabelType.all,
              leading: const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: _Mark(),
              ),
              destinations: widget.items
                  .map((item) => NavigationRailDestination(icon: Icon(item.icon), label: Text(item.label)))
                  .toList(),
            ),
            const VerticalDivider(width: 1),
            Expanded(child: content),
          ],
        ),
      );
    }

    return Scaffold(
      body: Row(
        children: [
          SizedBox(
            width: ArmxTheme.sidebarWidth,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Padding(padding: EdgeInsets.all(16), child: _Mark(showName: true)),
                Expanded(
                  child: ListView(
                    children: [
                      for (var i = 0; i < widget.items.length; i++)
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
                          child: ListTile(
                            selected: i == _index,
                            selectedTileColor: ArmxColors.accent.withOpacity(0.12),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(ArmxTheme.radiusMd)),
                            leading: Icon(widget.items[i].icon),
                            title: Text(widget.items[i].label),
                            onTap: () => _select(i),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const VerticalDivider(width: 1),
          Expanded(
            child: Column(
              children: [
                AppBar(title: Text(widget.items[_index].label), actions: widget.actions, elevation: 0),
                Expanded(child: content),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Mark extends StatelessWidget {
  const _Mark({this.showName = false});
  final bool showName;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          height: 36,
          width: 36,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: ArmxColors.accent,
            borderRadius: BorderRadius.circular(ArmxTheme.radiusMd),
          ),
          child: const Text('A', style: TextStyle(color: ArmxColors.ink, fontWeight: FontWeight.w800)),
        ),
        if (showName) ...[
          const SizedBox(width: 10),
          Text('A.R.M.X AI', style: Theme.of(context).textTheme.titleMedium),
        ],
      ],
    );
  }
}
