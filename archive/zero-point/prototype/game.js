/**
 * Zero-Point Game Logic
 * Comfort Test MVP
 */

class Game {
  constructor() {
    this.canvas = document.getElementById('game-canvas');
    this.ctx = this.canvas.getContext('2d');
    
    this.world = new PhysicsWorld(this.canvas.width, this.canvas.height);
    
    // Game objects
    this.seed = null;
    this.pot = null;
    this.obstacles = [];
    
    // Game state
    this.startTime = Date.now();
    this.attempts = 0;
    this.won = false;
    this.winTimer = 0;
    this.winThreshold = 60; // frames seed must stay in pot
    
    // Audio context for dynamic sound
    this.audioCtx = null;
    this.oscillators = [];
    
    this.setupWorld();
    this.setupUI();
    this.setupAudio();
    
    // Start game loop
    this.lastTime = performance.now();
    requestAnimationFrame((t) => this.loop(t));
  }

  setupWorld() {
    // Create seed (player object)
    this.seed = new Body(100, 300, 15, 1);
    this.seed.color = '#00ff88';
    this.world.addBody(this.seed);
    
    // Create pot (goal) - represented as a static zone
    this.pot = {
      x: 680,
      y: 480,
      width: 80,
      height: 100,
      openingWidth: 70
    };
    
    // Add some obstacles/platforms
    this.addObstacles();
  }

  addObstacles() {
    // Platform 1 - middle left
    const p1 = new Body(250, 400, 60, 100);
    p1.color = '#444';
    this.world.addStaticBody(p1);
    this.obstacles.push(p1);
    
    // Platform 2 - upper middle
    const p2 = new Body(450, 250, 50, 100);
    p2.color = '#444';
    this.world.addStaticBody(p2);
    this.obstacles.push(p2);
    
    // Platform 3 - bouncy ball
    const p3 = new Body(600, 350, 35, 50);
    p3.color = '#ff6b00';
    this.world.addStaticBody(p3);
    this.obstacles.push(p3);
    
    // Small stepping stones
    const p4 = new Body(180, 500, 25, 50);
    p4.color = '#444';
    this.world.addStaticBody(p4);
    this.obstacles.push(p4);
    
    const p5 = new Body(350, 520, 30, 50);
    p5.color = '#444';
    this.world.addStaticBody(p5);
    this.obstacles.push(p5);
  }

  setupUI() {
    // Slider bindings
    const sliders = ['gravity', 'friction', 'viscosity', 'elasticity', 'timescale'];
    
    sliders.forEach(name => {
      const slider = document.getElementById(name);
      const valueDisplay = document.getElementById(`${name}-value`);
      
      slider.addEventListener('input', () => {
        const val = parseInt(slider.value);
        valueDisplay.textContent = val;
        this.world.chaos[name] = val;
        this.world.updateConstants();
        this.updateAudio();
      });
    });
    
    // Reset button
    document.getElementById('reset-btn').addEventListener('click', () => {
      this.resetSeed();
    });
    
    // Launch button
    document.getElementById('launch-btn').addEventListener('click', () => {
      this.launchSeed();
    });
  }

  setupAudio() {
    try {
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      
      // Create ambient drone
      this.droneGain = this.audioCtx.createGain();
      this.droneGain.gain.value = 0.05;
      this.droneGain.connect(this.audioCtx.destination);
      
      // Low drone oscillator
      this.drone = this.audioCtx.createOscillator();
      this.drone.type = 'sine';
      this.drone.frequency.value = 60;
      
      // Filter for viscosity effect
      this.filter = this.audioCtx.createBiquadFilter();
      this.filter.type = 'lowpass';
      this.filter.frequency.value = 2000;
      
      this.drone.connect(this.filter);
      this.filter.connect(this.droneGain);
      this.drone.start();
      
    } catch (e) {
      console.log('Audio not available');
    }
  }

  updateAudio() {
    if (!this.audioCtx) return;
    
    // Time scale affects pitch
    const timescale = this.world.chaos.timescale / 100;
    const pitch = 40 + (1 - timescale) * 40; // slower = lower pitch
    this.drone.frequency.setTargetAtTime(pitch, this.audioCtx.currentTime, 0.1);
    
    // Viscosity affects filter
    const viscosity = this.world.chaos.viscosity / 100;
    const filterFreq = 500 + (1 - viscosity) * 3000;
    this.filter.frequency.setTargetAtTime(filterFreq, this.audioCtx.currentTime, 0.1);
  }

  playBounceSound(intensity) {
    if (!this.audioCtx) return;
    
    const osc = this.audioCtx.createOscillator();
    const gain = this.audioCtx.createGain();
    
    osc.type = 'sine';
    osc.frequency.value = 200 + intensity * 300;
    
    gain.gain.value = Math.min(0.3, intensity * 0.1);
    gain.gain.exponentialDecayTo = 0.001;
    
    osc.connect(gain);
    gain.connect(this.audioCtx.destination);
    
    osc.start();
    gain.gain.setTargetAtTime(0.001, this.audioCtx.currentTime, 0.1);
    osc.stop(this.audioCtx.currentTime + 0.2);
  }

  resetSeed() {
    this.seed.pos = new Vec2(100, 300);
    this.seed.vel = new Vec2(0, 0);
    this.seed.acc = new Vec2(0, 0);
    this.seed.temperature = 20;
    this.seed.internalEnergy = 0;
    this.seed.trail = [];
    this.attempts++;
    this.won = false;
    this.winTimer = 0;
    document.getElementById('win-message').classList.add('hidden');
    document.getElementById('attempt-count').textContent = this.attempts;
  }

  launchSeed() {
    this.attempts++;
    document.getElementById('attempt-count').textContent = this.attempts;
    
    // Launch toward pot with some randomness based on current physics
    const baseForce = 300;
    const angle = -Math.PI / 4 + (Math.random() - 0.5) * 0.3;
    
    this.seed.vel = new Vec2(
      Math.cos(angle) * baseForce,
      Math.sin(angle) * baseForce
    );
    
    // Resume audio context if suspended
    if (this.audioCtx && this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
  }

  checkWinCondition() {
    // Check if seed is inside pot opening
    const pot = this.pot;
    const seed = this.seed;
    
    const inPotX = seed.pos.x > pot.x - pot.openingWidth/2 && 
                   seed.pos.x < pot.x + pot.openingWidth/2;
    const inPotY = seed.pos.y > pot.y - pot.height/2 && 
                   seed.pos.y < pot.y + pot.height/2;
    const settledSpeed = seed.vel.len() < 50;
    
    if (inPotX && inPotY && settledSpeed) {
      this.winTimer++;
      if (this.winTimer >= this.winThreshold && !this.won) {
        this.won = true;
        document.getElementById('win-message').classList.remove('hidden');
        this.playWinSound();
      }
    } else {
      this.winTimer = Math.max(0, this.winTimer - 2);
    }
  }

  playWinSound() {
    if (!this.audioCtx) return;
    
    const notes = [523, 659, 784, 1047]; // C5, E5, G5, C6
    
    notes.forEach((freq, i) => {
      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();
      
      osc.type = 'sine';
      osc.frequency.value = freq;
      
      gain.gain.value = 0;
      gain.gain.setTargetAtTime(0.2, this.audioCtx.currentTime + i * 0.1, 0.01);
      gain.gain.setTargetAtTime(0, this.audioCtx.currentTime + i * 0.1 + 0.3, 0.1);
      
      osc.connect(gain);
      gain.connect(this.audioCtx.destination);
      
      osc.start(this.audioCtx.currentTime + i * 0.1);
      osc.stop(this.audioCtx.currentTime + i * 0.1 + 0.5);
    });
  }

  loop(currentTime) {
    const dt = Math.min((currentTime - this.lastTime) / 1000, 0.1);
    this.lastTime = currentTime;
    
    // Update physics
    this.world.step(dt);
    
    // Check win
    this.checkWinCondition();
    
    // Update timer display
    const elapsed = ((Date.now() - this.startTime) / 1000).toFixed(1);
    document.getElementById('time-display').textContent = elapsed;
    
    // Render
    this.render();
    
    requestAnimationFrame((t) => this.loop(t));
  }

  render() {
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    
    // Clear with slight trail effect
    ctx.fillStyle = 'rgba(10, 10, 21, 0.3)';
    ctx.fillRect(0, 0, w, h);
    
    // Draw grid (subtle)
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
    ctx.lineWidth = 1;
    for (let x = 0; x < w; x += 50) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += 50) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
    
    // Draw pot
    this.drawPot();
    
    // Draw obstacles
    for (const obs of this.obstacles) {
      this.drawBody(obs);
    }
    
    // Draw seed trail
    this.drawTrail(this.seed);
    
    // Draw seed
    this.drawSeed();
    
    // Draw UI overlays
    this.drawOverlays();
  }

  drawPot() {
    const ctx = this.ctx;
    const pot = this.pot;
    
    // Pot glow when seed is close
    const dist = Math.hypot(this.seed.pos.x - pot.x, this.seed.pos.y - pot.y);
    const glowIntensity = Math.max(0, 1 - dist / 300);
    
    // Pot body
    ctx.save();
    ctx.translate(pot.x, pot.y);
    
    // Glow
    if (glowIntensity > 0) {
      ctx.shadowColor = '#00ff88';
      ctx.shadowBlur = 20 * glowIntensity;
    }
    
    // Draw pot shape
    ctx.fillStyle = this.won ? '#00ff88' : '#553300';
    ctx.strokeStyle = this.won ? '#00ff88' : '#884400';
    ctx.lineWidth = 3;
    
    ctx.beginPath();
    // Pot outline (trapezoid)
    ctx.moveTo(-pot.openingWidth/2, -pot.height/2);
    ctx.lineTo(-pot.width/2, pot.height/2);
    ctx.lineTo(pot.width/2, pot.height/2);
    ctx.lineTo(pot.openingWidth/2, -pot.height/2);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    
    // Pot opening indicator
    ctx.strokeStyle = this.won ? '#00ff88' : '#ffaa00';
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(-pot.openingWidth/2, -pot.height/2);
    ctx.lineTo(pot.openingWidth/2, -pot.height/2);
    ctx.stroke();
    ctx.setLineDash([]);
    
    // Win progress indicator
    if (this.winTimer > 0 && !this.won) {
      const progress = this.winTimer / this.winThreshold;
      ctx.fillStyle = `rgba(0, 255, 136, ${progress})`;
      ctx.fillRect(-pot.width/2, pot.height/2 - pot.height * progress, pot.width, pot.height * progress);
    }
    
    ctx.restore();
  }

  drawBody(body) {
    const ctx = this.ctx;
    
    ctx.save();
    ctx.translate(body.pos.x, body.pos.y);
    
    // Temperature-based color shift
    const heat = Math.min(1, (body.temperature - 20) / 100);
    
    ctx.fillStyle = body.color;
    if (heat > 0) {
      ctx.shadowColor = `rgba(255, ${Math.floor(150 - heat * 150)}, 0, ${heat})`;
      ctx.shadowBlur = heat * 20;
    }
    
    ctx.beginPath();
    ctx.arc(0, 0, body.radius, 0, Math.PI * 2);
    ctx.fill();
    
    ctx.restore();
  }

  drawTrail(body) {
    const ctx = this.ctx;
    const trail = body.trail;
    
    if (trail.length < 2) return;
    
    ctx.save();
    ctx.strokeStyle = body.color;
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    
    for (let i = 1; i < trail.length; i++) {
      const alpha = i / trail.length * 0.5;
      ctx.strokeStyle = `rgba(0, 255, 136, ${alpha})`;
      ctx.beginPath();
      ctx.moveTo(trail[i-1].x, trail[i-1].y);
      ctx.lineTo(trail[i].x, trail[i].y);
      ctx.stroke();
    }
    
    ctx.restore();
  }

  drawSeed() {
    const ctx = this.ctx;
    const seed = this.seed;
    
    ctx.save();
    ctx.translate(seed.pos.x, seed.pos.y);
    
    // Glow based on speed and temperature
    const speed = seed.vel.len();
    const heat = (seed.temperature - 20) / 50;
    const glowIntensity = Math.min(1, speed / 500 + heat);
    
    // Outer glow
    const gradient = ctx.createRadialGradient(0, 0, seed.radius * 0.5, 0, 0, seed.radius * 2);
    gradient.addColorStop(0, `rgba(0, 255, 136, ${0.8 + glowIntensity * 0.2})`);
    gradient.addColorStop(0.5, `rgba(0, 255, 136, ${0.3 * glowIntensity})`);
    gradient.addColorStop(1, 'rgba(0, 255, 136, 0)');
    
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(0, 0, seed.radius * 2, 0, Math.PI * 2);
    ctx.fill();
    
    // Core
    ctx.fillStyle = seed.color;
    ctx.shadowColor = seed.color;
    ctx.shadowBlur = 10 + glowIntensity * 20;
    ctx.beginPath();
    ctx.arc(0, 0, seed.radius, 0, Math.PI * 2);
    ctx.fill();
    
    // Inner highlight
    ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
    ctx.beginPath();
    ctx.arc(-seed.radius * 0.3, -seed.radius * 0.3, seed.radius * 0.4, 0, Math.PI * 2);
    ctx.fill();
    
    // Speed indicator (motion blur direction)
    if (speed > 50) {
      const velNorm = seed.vel.norm();
      ctx.strokeStyle = `rgba(0, 255, 136, ${Math.min(0.5, speed/1000)})`;
      ctx.lineWidth = seed.radius * 0.5;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(-velNorm.x * speed * 0.05, -velNorm.y * speed * 0.05);
      ctx.stroke();
    }
    
    ctx.restore();
  }

  drawOverlays() {
    const ctx = this.ctx;
    
    // Physics state indicator (top-left)
    ctx.save();
    ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
    ctx.font = '12px monospace';
    
    const chaos = this.world.chaos;
    const consts = this.world.constants;
    
    ctx.fillText(`g: ${consts.gravity.toFixed(0)}`, 10, 20);
    ctx.fillText(`μ: ${consts.friction.toFixed(2)}`, 10, 35);
    ctx.fillText(`η: ${consts.drag.toFixed(4)}`, 10, 50);
    ctx.fillText(`e: ${consts.restitution.toFixed(2)}`, 10, 65);
    ctx.fillText(`t: ${consts.timeScale.toFixed(2)}x`, 10, 80);
    
    // Seed state
    ctx.fillText(`vel: ${this.seed.vel.len().toFixed(0)}`, 10, 100);
    ctx.fillText(`temp: ${this.seed.temperature.toFixed(0)}°`, 10, 115);
    
    ctx.restore();
    
    // Extreme value warning
    const extremeG = chaos.gravity < 10 || chaos.gravity > 90;
    const extremeE = chaos.elasticity > 90;
    const extremeT = chaos.timescale < 10 || chaos.timescale > 90;
    
    if (extremeG || extremeE || extremeT) {
      // Post-processing effect simulation: draw vignette
      const gradient = ctx.createRadialGradient(
        this.canvas.width/2, this.canvas.height/2, this.canvas.height * 0.3,
        this.canvas.width/2, this.canvas.height/2, this.canvas.height * 0.8
      );
      gradient.addColorStop(0, 'rgba(0, 0, 0, 0)');
      gradient.addColorStop(1, 'rgba(255, 0, 230, 0.1)');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    }
  }
}

// Initialize game when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  window.game = new Game();
});
