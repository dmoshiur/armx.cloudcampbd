import 'package:flutter/material.dart';

import '../../core/theme.dart';

/// Floating assistant bubble (Android overlay window).
///
/// Implemented as a self-contained widget so the overlay isolate can show the
/// same UI. The bubble is always visible while active - the platform shows its
/// own ongoing notification, and the user can close it at any moment.
class OverlayBubble extends StatelessWidget {
  const OverlayBubble({super.key, required this.onTap, required this.onClose, this.status = 'idle'});

  final VoidCallback onTap;
  final VoidCallback onClose;
  final String status;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          GestureDetector(
            onTap: onTap,
            child: Container(
              height: 60,
              width: 60,
              decoration: BoxDecoration(
                color: ArmxColors.accent,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(color: Colors.black.withOpacity(0.35), blurRadius: 16, offset: const Offset(0, 6)),
                ],
              ),
              child: Icon(
                status == 'listening' ? Icons.mic : Icons.auto_awesome,
                color: ArmxColors.ink,
              ),
            ),
          ),
          Positioned(
            top: -6,
            right: -6,
            child: GestureDetector(
              onTap: onClose,
              child: Container(
                height: 22,
                width: 22,
                decoration: const BoxDecoration(color: ArmxColors.ink, shape: BoxShape.circle),
                child: const Icon(Icons.close, size: 14, color: ArmxColors.fog),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
