import 'package:flutter/material.dart';

/// Design tokens. These mirror `design/tokens.json` exactly - the single source
/// of truth shared with the web app and the deploy pipeline's design lint.
class ArmxColors {
  static const ink = Color(0xFF020904);
  static const navy = Color(0xFF06120A);
  static const accent = Color(0xFF00FF41);
  static const accent2 = Color(0xFF00B82E);
  static const fog = Color(0xFFD7FFE1);
  static const line = Color(0xFF174D24);
  static const muted = Color(0xFF75A881);
  static const success = Color(0xFF00D938);
  static const warning = Color(0xFFF5C542);
  static const danger = Color(0xFFFF4D67);
}

class ArmxTheme {
  static const double radiusSm = 8;
  static const double radiusMd = 12;
  static const double radiusLg = 16;
  static const double touchTarget = 48;
  static const double contentMaxWidth = 1200;
  static const double sidebarWidth = 264;
  static const double railWidth = 84;

  static ThemeData dark() => _build(Brightness.dark);
  static ThemeData light() => _build(Brightness.light);

  static ThemeData _build(Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    final background = isDark ? ArmxColors.ink : const Color(0xFFECFFF0);
    final surface = isDark ? ArmxColors.navy : Colors.white;
    final text = isDark ? ArmxColors.fog : ArmxColors.ink;
    final textMuted = isDark ? ArmxColors.muted : const Color(0xFF386B45);
    final border = isDark ? ArmxColors.line : const Color(0xFFA8DDB4);

    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: ColorScheme.fromSeed(
        seedColor: ArmxColors.accent,
        brightness: brightness,
        primary: ArmxColors.accent,
        onPrimary: ArmxColors.ink,
        surface: surface,
        onSurface: text,
        error: ArmxColors.danger,
      ),
      scaffoldBackgroundColor: Colors.transparent,
      fontFamily: 'Inter',
    );

    return base.copyWith(
      textTheme: base.textTheme.copyWith(
        displayLarge: TextStyle(fontSize: 44, height: 1.1, letterSpacing: -0.02 * 44, fontWeight: FontWeight.w700, color: text),
        headlineLarge: TextStyle(fontSize: 32, height: 1.2, letterSpacing: -0.015 * 32, fontWeight: FontWeight.w700, color: text),
        headlineMedium: TextStyle(fontSize: 24, height: 1.25, letterSpacing: -0.01 * 24, fontWeight: FontWeight.w600, color: text),
        titleMedium: TextStyle(fontSize: 18, height: 1.35, fontWeight: FontWeight.w600, color: text),
        bodyMedium: TextStyle(fontSize: 15, height: 1.5, color: text),
        bodySmall: TextStyle(fontSize: 13, height: 1.45, color: textMuted),
      ),
      cardTheme: CardThemeData(
        color: surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(radiusLg),
          side: BorderSide(color: border),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: ArmxColors.accent,
          foregroundColor: ArmxColors.ink,
          minimumSize: const Size(0, touchTarget),
          padding: const EdgeInsets.symmetric(horizontal: 20),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusMd)),
          textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
          elevation: 0,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: text,
          minimumSize: const Size(0, touchTarget),
          side: BorderSide(color: border),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusMd)),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: background,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusMd),
          borderSide: BorderSide(color: border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusMd),
          borderSide: BorderSide(color: border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(radiusMd),
          borderSide: const BorderSide(color: ArmxColors.accent, width: 2),
        ),
      ),
      dividerTheme: DividerThemeData(color: border, thickness: 1, space: 1),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: surface,
        contentTextStyle: TextStyle(color: text),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radiusMd)),
      ),
    );
  }
}
