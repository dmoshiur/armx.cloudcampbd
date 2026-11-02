import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';

/// Full-screen CMatrix ambience. It is decorative, ignores pointer events and
/// stops completely when the platform requests reduced motion.
class MatrixBackground extends StatefulWidget {
  const MatrixBackground({required this.child, super.key});

  final Widget child;

  @override
  State<MatrixBackground> createState() => _MatrixBackgroundState();
}

class _MatrixBackgroundState extends State<MatrixBackground>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 22),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _controller.stop();
      _controller.value = 0.35;
    } else if (!_controller.isAnimating) {
      _controller.repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return ColoredBox(
      color: dark ? ArmxColors.ink : const Color(0xFFECFFF0),
      child: Stack(
        fit: StackFit.expand,
        children: [
          IgnorePointer(
            child: AnimatedBuilder(
              animation: _controller,
              builder: (_, __) => CustomPaint(
                painter: _MatrixPainter(progress: _controller.value, dark: dark),
              ),
            ),
          ),
          widget.child,
        ],
      ),
    );
  }
}

class _MatrixPainter extends CustomPainter {
  const _MatrixPainter({required this.progress, required this.dark});

  final double progress;
  final bool dark;
  static const _glyphs = '01ARＭＸアイウエオカキクケコ';

  @override
  void paint(Canvas canvas, Size size) {
    final columns = math.max(8, (size.width / 42).ceil());
    for (var column = 0; column < columns; column++) {
      final random = math.Random(column * 7919 + 17);
      final x = column * (size.width / columns) + 3;
      final speed = 0.55 + random.nextDouble() * 1.4;
      final length = 5 + random.nextInt(10);
      final phase = random.nextDouble();
      final track = size.height + length * 25;
      final head = ((progress * speed + phase) % 1) * track - length * 25;
      for (var row = 0; row < length; row++) {
        final opacity = (1 - row / length) * (dark ? 0.13 : 0.07);
        final painter = TextPainter(
          text: TextSpan(
            text: _glyphs[(column + row * 3) % _glyphs.length],
            style: TextStyle(
              color: ArmxColors.accent.withValues(alpha: opacity),
              fontFamily: 'monospace',
              fontSize: 13,
            ),
          ),
          textDirection: TextDirection.ltr,
        )..layout();
        painter.paint(canvas, Offset(x, head - row * 25));
      }
    }
  }

  @override
  bool shouldRepaint(_MatrixPainter oldDelegate) =>
      oldDelegate.progress != progress || oldDelegate.dark != dark;
}
