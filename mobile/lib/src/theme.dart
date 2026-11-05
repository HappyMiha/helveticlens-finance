// Helvetic Lens dark tokens (same values as design-tokens.css).
import 'package:flutter/material.dart';

class T {
  static const bg = Color(0xFF090B0E);
  static const surface = Color(0xFF111418);
  static const surface2 = Color(0xFF181A1E);
  static const line = Color(0xFF343A44);
  static const text = Color(0xFFE6E3E1);
  static const muted = Color(0xFFA7ADB5);
  static const success = Color(0xFFA4D2B7);
  static const warning = Color(0xFFE6C083);
  static const danger = Color(0xFFF2B0A9);
  static const expense = [Color(0xFF7A2F2A), Color(0xFF8A4127), Color(0xFF6F3A2C), Color(0xFF93502A), Color(0xFF5F2F2F)];

  static ThemeData theme() => ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: bg,
        colorScheme: const ColorScheme.dark(primary: text, onPrimary: bg, surface: surface, onSurface: text, error: danger),
        cardTheme: const CardThemeData(color: surface, shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(14)), side: BorderSide(color: line))),
        appBarTheme: const AppBarTheme(backgroundColor: bg, foregroundColor: text, elevation: 0),
        navigationBarTheme: const NavigationBarThemeData(backgroundColor: surface, indicatorColor: surface2),
        useMaterial3: true,
      );

  static String chf(Object? value) {
    final v = double.tryParse('$value') ?? 0; // display only; every amount comes computed from the ledger
    final neg = v < 0;
    final parts = v.abs().toStringAsFixed(2).split('.');
    final whole = parts[0].replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => '’');
    return '${neg ? '-' : ''}CHF $whole.${parts[1]}';
  }

  static Color status(String? s) => s == 'confirmed' ? success : s == 'needs_review' ? warning : muted;
  static String statusLabel(String? s) =>
      {'confirmed': 'Confirmed', 'needs_review': 'Needs review', 'unconfirmed': 'Unconfirmed'}[s] ?? (s ?? '');
}
