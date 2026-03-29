/**
 * Zero-Point Physics Engine
 * Minimal deterministic 2D physics with coupled constants
 */

class Vec2 {
  constructor(x = 0, y = 0) {
    this.x = x;
    this.y = y;
  }

  add(v) { return new Vec2(this.x + v.x, this.y + v.y); }
  sub(v) { return new Vec2(this.x - v.x, this.y - v.y); }
  mul(s) { return new Vec2(this.x * s, this.y * s); }
  dot(v) { return this.x * v.x + this.y * v.y; }
  len() { return Math.sqrt(this.x * this.x + this.y * this.y); }
  norm() { const l = this.len(); return l > 0 ? this.mul(1/l) : new Vec2(); }
  clone() { return new Vec2(this.x, this.y); }
}

class Body {
  constructor(x, y, radius, mass = 1) {
    this.pos = new Vec2(x, y);
    this.prevPos = new Vec2(x, y);
    this.vel = new Vec2();
    this.acc = new Vec2();
    this.radius = radius;
    this.baseMass = mass;
    this.mass = mass;
    this.internalEnergy = 0;
    this.temperature = 20; // Celsius
    this.baseRadius = radius;
    this.isStatic = false;
    this.color = '#00d9ff';
    this.trail = [];
    this.maxTrail = 30;
  }

  applyForce(force) {
    this.acc = this.acc.add(force.mul(1 / this.mass));
  }
}

class PhysicsWorld {
  constructor(width, height) {
    this.width = width;
    this.height = height;
    this.bodies = [];
    this.staticBodies = [];
    this.constraints = [];
    
    // Chaos Table values (0-100 normalized)
    this.chaos = {
      gravity: 50,
      friction: 50,
      viscosity: 50,
      elasticity: 50,
      timescale: 50
    };
    
    // Derived physics constants
    this.constants = {};
    this.updateConstants();
    
    // Fixed timestep for determinism
    this.fixedDt = 1/120;
    this.accumulator = 0;
    
    // Boundaries
    this.bounds = {
      left: 0,
      right: width,
      top: 0,
      bottom: height
    };
  }

  updateConstants() {
    // Map 0-100 sliders to physics values with non-linear curves
    const g = this.chaos.gravity / 100;
    const mu = this.chaos.friction / 100;
    const eta = this.chaos.viscosity / 100;
    const e = this.chaos.elasticity / 100;
    const t = this.chaos.timescale / 100;
    
    // Gravity: 0 = micro-gravity, 50 = earth-like, 100 = crushing
    this.constants.gravity = g * g * 2000; // 0 to 2000
    
    // Friction coefficient: affects velocity damping and heat generation
    this.constants.friction = mu * mu; // 0 to 1
    this.constants.heatGeneration = mu * 0.5; // friction generates heat
    
    // Viscosity/drag: air resistance
    this.constants.drag = eta * eta * 0.05; // 0 to 0.05
    
    // Elasticity/restitution: bounce factor
    // Allow super-elastic (>1) at high values for fun
    this.constants.restitution = 0.1 + e * e * 1.4; // 0.1 to 1.5
    
    // Time scale: affects simulation speed
    // Low slider = fast forward, High slider = slow motion
    this.constants.timeScale = 0.1 + (1 - t) * 2.9; // 0.1 (slow) to 3.0 (fast)
  }

  addBody(body) {
    this.bodies.push(body);
    return body;
  }

  addStaticBody(body) {
    body.isStatic = true;
    this.staticBodies.push(body);
    return body;
  }

  step(dt) {
    // Apply time scale
    dt *= this.constants.timeScale;
    
    // Accumulate time for fixed timestep
    this.accumulator += dt;
    
    let steps = 0;
    while (this.accumulator >= this.fixedDt && steps < 10) {
      this.fixedStep(this.fixedDt);
      this.accumulator -= this.fixedDt;
      steps++;
    }
  }

  fixedStep(dt) {
    const gravity = new Vec2(0, this.constants.gravity);
    
    for (const body of this.bodies) {
      if (body.isStatic) continue;
      
      // Store trail
      body.trail.push(body.pos.clone());
      if (body.trail.length > body.maxTrail) {
        body.trail.shift();
      }
      
      // Apply gravity (scaled by mass for weight effect)
      body.applyForce(gravity.mul(body.mass));
      
      // Apply drag (viscosity)
      const speed = body.vel.len();
      if (speed > 0) {
        const dragForce = body.vel.norm().mul(-this.constants.drag * speed * speed * body.radius);
        body.applyForce(dragForce);
      }
      
      // Integrate (Verlet-style for stability)
      const newVel = body.vel.add(body.acc.mul(dt));
      body.pos = body.pos.add(newVel.mul(dt));
      body.vel = newVel;
      body.acc = new Vec2();
      
      // Thermal: cool down over time
      body.temperature = Math.max(20, body.temperature - dt * 5);
      body.internalEnergy = Math.max(0, body.internalEnergy - dt * 10);
      
      // Thermal expansion
      const expansion = 1 + (body.temperature - 20) * 0.002;
      body.radius = body.baseRadius * expansion;
      body.mass = body.baseMass * expansion * expansion;
    }
    
    // Collision detection and response
    this.resolveCollisions();
    
    // Boundary collisions
    this.resolveBoundaries();
  }

  resolveCollisions() {
    // Body vs Body
    for (let i = 0; i < this.bodies.length; i++) {
      for (let j = i + 1; j < this.bodies.length; j++) {
        this.collide(this.bodies[i], this.bodies[j]);
      }
    }
    
    // Body vs Static
    for (const body of this.bodies) {
      for (const staticBody of this.staticBodies) {
        this.collide(body, staticBody);
      }
    }
  }

  collide(a, b) {
    const diff = b.pos.sub(a.pos);
    const dist = diff.len();
    const minDist = a.radius + b.radius;
    
    if (dist < minDist && dist > 0) {
      const normal = diff.norm();
      const overlap = minDist - dist;
      
      // Separate bodies
      if (!a.isStatic && !b.isStatic) {
        const totalMass = a.mass + b.mass;
        a.pos = a.pos.sub(normal.mul(overlap * b.mass / totalMass));
        b.pos = b.pos.add(normal.mul(overlap * a.mass / totalMass));
      } else if (!a.isStatic) {
        a.pos = a.pos.sub(normal.mul(overlap));
      } else if (!b.isStatic) {
        b.pos = b.pos.add(normal.mul(overlap));
      }
      
      // Relative velocity
      const relVel = a.vel.sub(b.vel);
      const velAlongNormal = relVel.dot(normal);
      
      // Only resolve if approaching
      if (velAlongNormal > 0) return;
      
      // Restitution (elasticity)
      const e = this.constants.restitution;
      
      // Impulse magnitude
      let j = -(1 + e) * velAlongNormal;
      if (!a.isStatic && !b.isStatic) {
        j /= (1/a.mass + 1/b.mass);
      } else {
        j /= a.isStatic ? (1/b.mass) : (1/a.mass);
      }
      
      // Apply impulse
      const impulse = normal.mul(j);
      if (!a.isStatic) {
        a.vel = a.vel.sub(impulse.mul(1/a.mass));
      }
      if (!b.isStatic) {
        b.vel = b.vel.add(impulse.mul(1/b.mass));
      }
      
      // Friction (tangent impulse)
      const tangent = relVel.sub(normal.mul(velAlongNormal)).norm();
      let jt = -relVel.dot(tangent);
      if (!a.isStatic && !b.isStatic) {
        jt /= (1/a.mass + 1/b.mass);
      } else {
        jt /= a.isStatic ? (1/b.mass) : (1/a.mass);
      }
      
      // Clamp friction
      const frictionImpulse = Math.abs(jt) < Math.abs(j) * this.constants.friction
        ? tangent.mul(jt)
        : tangent.mul(-j * this.constants.friction);
      
      if (!a.isStatic) {
        a.vel = a.vel.sub(frictionImpulse.mul(1/a.mass));
      }
      if (!b.isStatic) {
        b.vel = b.vel.add(frictionImpulse.mul(1/b.mass));
      }
      
      // Heat generation from collision
      const impactEnergy = Math.abs(velAlongNormal) * this.constants.heatGeneration * 10;
      if (!a.isStatic) {
        a.internalEnergy += impactEnergy;
        a.temperature += impactEnergy * 0.5;
      }
      if (!b.isStatic) {
        b.internalEnergy += impactEnergy;
        b.temperature += impactEnergy * 0.5;
      }
    }
  }

  resolveBoundaries() {
    for (const body of this.bodies) {
      if (body.isStatic) continue;
      
      const e = this.constants.restitution;
      const friction = this.constants.friction;
      
      // Left wall
      if (body.pos.x - body.radius < this.bounds.left) {
        body.pos.x = this.bounds.left + body.radius;
        body.vel.x = -body.vel.x * e;
        body.vel.y *= (1 - friction * 0.5);
        this.addCollisionHeat(body, Math.abs(body.vel.x));
      }
      
      // Right wall
      if (body.pos.x + body.radius > this.bounds.right) {
        body.pos.x = this.bounds.right - body.radius;
        body.vel.x = -body.vel.x * e;
        body.vel.y *= (1 - friction * 0.5);
        this.addCollisionHeat(body, Math.abs(body.vel.x));
      }
      
      // Top wall
      if (body.pos.y - body.radius < this.bounds.top) {
        body.pos.y = this.bounds.top + body.radius;
        body.vel.y = -body.vel.y * e;
        body.vel.x *= (1 - friction * 0.5);
        this.addCollisionHeat(body, Math.abs(body.vel.y));
      }
      
      // Bottom wall (floor)
      if (body.pos.y + body.radius > this.bounds.bottom) {
        body.pos.y = this.bounds.bottom - body.radius;
        body.vel.y = -body.vel.y * e;
        body.vel.x *= (1 - friction * 0.5);
        this.addCollisionHeat(body, Math.abs(body.vel.y));
      }
    }
  }

  addCollisionHeat(body, impactSpeed) {
    const heat = impactSpeed * this.constants.heatGeneration * 5;
    body.internalEnergy += heat;
    body.temperature += heat * 0.3;
  }
}

// Export for use
window.Vec2 = Vec2;
window.Body = Body;
window.PhysicsWorld = PhysicsWorld;
