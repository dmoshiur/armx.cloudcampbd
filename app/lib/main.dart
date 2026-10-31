import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/api_client.dart';
import 'core/app_state.dart';
import 'core/theme.dart';
import 'core/widgets/adaptive_scaffold.dart';
import 'features/admin/admin_screen.dart';
import 'features/alarms/alarms_screen.dart';
import 'features/assistant/chat_screen.dart';
import 'features/auth/login_screen.dart';
import 'features/devices/devices_screen.dart';
import 'features/device_bridge/device_bridge.dart';
import 'features/guest_greeter/guest_greeter_screen.dart';
import 'features/messaging/messaging_screen.dart';
import 'features/settings/settings_screen.dart';
import 'features/smart_home/smart_home_screen.dart';
import 'features/voice/wake_word_service.dart';
import 'features/web_builder/builder_screen.dart';

void main() {
  runApp(const ArmxApp());
}

class ArmxApp extends StatelessWidget {
  const ArmxApp({super.key});

  @override
  Widget build(BuildContext context) {
    final api = ApiClient(baseUrl: defaultApiBase());

    return MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => AuthController(api)..bootstrap()),
        ChangeNotifierProvider(create: (_) => WakeWordService()),
        ChangeNotifierProvider(create: (_) => DeviceBridge(api)..init()),
      ],
      child: Consumer<AuthController>(
        builder: (context, auth, _) {
          final theme = auth.themeMode == 'light' ? ArmxTheme.light() : ArmxTheme.dark();
          return MaterialApp(
            title: 'A.R.M.X AI',
            debugShowCheckedModeBanner: false,
            theme: theme,
            home: auth.status == AuthStatus.signedIn
                ? const _Home()
                : LoginScreen(apiBase: api.baseUrl, onNeedsSignup: () {}),
          );
        },
      ),
    );
  }
}

class _Home extends StatelessWidget {
  const _Home();

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();

    final items = <NavItem>[
      NavItem(label: 'Assistant', icon: Icons.auto_awesome_outlined, builder: (_) => const ChatScreen()),
      NavItem(label: 'Home', icon: Icons.lightbulb_outline, builder: (_) => const SmartHomeScreen()),
      NavItem(label: 'Devices', icon: Icons.devices_other_outlined, builder: (_) => const DevicesScreen()),
      NavItem(label: 'Alarms', icon: Icons.alarm_outlined, builder: (_) => const AlarmsScreen()),
      NavItem(label: 'Builder', icon: Icons.dashboard_customize_outlined, builder: (_) => const BuilderScreen()),
      NavItem(label: 'Messaging', icon: Icons.chat_bubble_outline, builder: (_) => const MessagingScreen()),
      NavItem(label: 'Guests', icon: Icons.doorbell_outlined, builder: (_) => const GuestGreeterScreen()),
      NavItem(label: 'Settings', icon: Icons.settings_outlined, builder: (_) => const SettingsScreen()),
      if (auth.user?.isAdmin == true)
        NavItem(label: 'Admin', icon: Icons.shield_outlined, builder: (_) => const AdminScreen()),
    ];

    return AdaptiveScaffold(
      title: 'A.R.M.X AI',
      items: items,
      actions: [
        IconButton(
          tooltip: 'Sign out',
          onPressed: auth.logout,
          icon: const Icon(Icons.logout),
        ),
      ],
    );
  }
}
