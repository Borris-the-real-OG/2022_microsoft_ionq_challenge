# -*- coding: utf-8 -*-
#
#  Map.py, Ice Emblem's map class.
#
#  Copyright 2015 Elia Argentieri <elia.argentieri@openmailbox.org>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.


import tmx
import pygame
import os.path
import logging
import utils
import heapq
from unit import Unit
from colors import *


class UnitSprite(pygame.sprite.Sprite):
	def __init__(self, size, obj, unit, team, *groups):
		"""
		size: sprite size in pixels
		obj: unit data from tmx
		unit: unit object
		groups: sprites layer
		"""
		super().__init__(*groups)

		self.unit = unit
		self.team = team
		w, h = size
		x, y = self.coord = (obj.px // w), (obj.py // h)
		pos = x * w, y * h

		self.image = pygame.Surface(size).convert_alpha()
		self.rect = rect = pygame.Rect(pos, size)

		self.update()

	def update(self, new_coord=None):
		if not self.unit.was_modified() and (not new_coord or new_coord == self.coord):
			return
		logging.debug("Sprite update: ", self.unit.name)
		if new_coord:
			self.coord = new_coord
			self.rect.topleft = self.coord[0] * self.rect.w, self.coord[1] * self.rect.h

		w, h = self.rect.size
		w2, h2 = w // 2, h // 2
		mw, mh = img_max_size = (w, h - 5)
		mw2, mh2 = mw // 2, mh // 2

		self.image.fill((0, 0, 0, 0))
		pygame.draw.circle(self.image, self.unit.color, (mw2, mh2), mh2, 3)

		src_img = self.unit.image
		if src_img is None:
			self.image.blit(src_img, utils.center(self.image.get_rect(), src_img.get_rect()))
		else:
			image_size = utils.resize_keep_ratio(src_img.get_size(), img_max_size)
			resized_image = pygame.transform.smoothscale(src_img, image_size).convert_alpha()
			self.image.blit(resized_image, utils.center(self.image.get_rect(), resized_image.get_rect()))

		hp_bar_length = int(self.unit.hp / self.unit.hp_max * self.rect.w)
		hp_bar = pygame.Surface((hp_bar_length, 5))
		hp_bar.fill((0, 255, 0))
		self.image.blit(hp_bar, (0, self.rect.h - 5))
		if self.team.is_boss(self.unit):
			icon = pygame.Surface((3, 3))
			icon.fill(BLUE)
			self.image.blit(icon, (0, self.rect.h - 4))


class Terrain(object):
	def __init__(self, tile, unit):
		self.name = tile.properties.get('name', _('Unknown'))
		self.moves = float(tile.properties.get('moves', 1))  # how many moves are required to move a unit through
		self.defense = int(tile.properties.get('defense', 0))  # bonus defense
		self.avoid = int(tile.properties.get('avoid', 0))  # bonus avoid
		self.allowed = tile.properties.get('allowed', _('any')).split(',')
		self.surface = tile.surface
		self.unit = unit


class Cursor(pygame.sprite.Sprite):
	def __init__(self, tilemap, img_path, *groups):
		super(Cursor, self).__init__(*groups)
		self.image = pygame.image.load(img_path).convert_alpha()
		self.tilesize = tilemap.tile_width, tilemap.tile_height
		self.rect = pygame.Rect((0, 0), self.tilesize)
		self.coord = (0, 0)
		self.tilemap = tilemap

	def update(self, event):
		if event.type == pygame.KEYDOWN:
			cx, cy = self.coord
			if event.key == pygame.K_UP:
				cx, cy = (cx, (cy - 1) % self.tilemap.height)
			elif event.key == pygame.K_DOWN:
				cx, cy = (cx, (cy + 1) % self.tilemap.height)
			elif event.key == pygame.K_LEFT:
				cx, cy = ((cx - 1) % self.tilemap.width, cy)
			elif event.key == pygame.K_RIGHT:
				cx, cy = ((cx + 1) % self.tilemap.width, cy)

			self.rect.x = cx * self.tilemap.tile_width
			self.rect.y = cy * self.tilemap.tile_height
			self.coord = cx, cy
		elif event.type == pygame.MOUSEMOTION:
			cx, cy = self.tilemap.index_at(*event.pos)
			if 0 <= cx < self.tilemap.width and 0 <= cy < self.tilemap.height:
				self.rect.x = cx * self.tilemap.tile_width
				self.rect.y = cy * self.tilemap.tile_height
				self.coord = cx, cy


class CellHighlight(pygame.sprite.Sprite):
	def __init__(self, tilemap, *groups):
		super(CellHighlight, self).__init__(*groups)

		self.w, self.h = tilemap.width, tilemap.height
		self.tile_size = self.tw, self.th = tilemap.tile_width, tilemap.tile_height

		self.highlight_colors = dict(selected=SELECTED, move=MOVE, attack=ATTACK, played=PLAYED)
		self.highlight_surfaces = {}
		for highlight, color in self.highlight_colors.items():
			self.highlight_surfaces[highlight] = pygame.Surface(self.tile_size).convert_alpha()
			self.highlight_surfaces[highlight].fill(color)

		self.horizontal_line = pygame.Surface((tilemap.px_width, 2)).convert_alpha()
		self.horizontal_line.fill((0, 0, 0, 100))
		self.vertical_line = pygame.Surface((2, tilemap.px_height)).convert_alpha()
		self.vertical_line.fill((0, 0, 0, 100))

		self.image = pygame.Surface((tilemap.px_width, tilemap.px_height)).convert_alpha()
		self.image.fill((0, 0, 0, 0))

		self.rect = pygame.Rect((0, 0), (tilemap.px_width, tilemap.px_height))
		self.update()

	def update(self, selected=None, move=[], attack=[], played=[]):
		self.image.fill((0, 0, 0, 0))

		blit = self.image.blit

		if selected is not None:
			x, y = selected
			blit(self.highlight_surfaces['selected'], (x * self.tw, y * self.th))

		for (x, y) in move:
			blit(self.highlight_surfaces['move'], (x * self.tw, y * self.th))

		for (x, y) in attack:
			blit(self.highlight_surfaces['attack'], (x * self.tw, y * self.th))

		for (x, y) in played:
			blit(self.highlight_surfaces['played'], (x * self.tw, y * self.th))

		for i in range(self.w):
			self.image.blit(self.vertical_line, (i * self.tw - 1, 0))
		for j in range(self.h):
			self.image.blit(self.horizontal_line, (0, j * self.th - 1))


class Arrow(pygame.sprite.Sprite):
	def __init__(self, screen_size, image_path, tilesize, *groups):
		super(Arrow, self).__init__(*groups)
		self.source_image = pygame.image.load(image_path)

		self.arrow = {}

		self.path = []
		self.source = None

		self.set_tilesize(tilesize)

		self.image = pygame.Surface(screen_size).convert_alpha()
		self.image.fill((0, 0, 0, 0))
		self.rect = pygame.Rect((0, 0), screen_size)

	def update(self, path, source=None):
		if self.path == path:
			return
		if source is not None:
			self.source = source
		self.path = path
		self.image.fill((0, 0, 0, 0))
		for (x, y) in self.path:
			img = self.get_arrow_part((x, y))
			pos = (x * self.tilesize[0], y * self.tilesize[1])
			self.image.blit(img, pos)

	def set_tilesize(self, tilesize):
		self.tilesize = tilesize
		w, h = self.source_image.get_size()
		rw, rh = rectsize = (w // 4, h // 4)

		arrow_parts = []
		for j in range(4):
			for i in range(4):
				pos = (i * rw, j * rh)
				rect = pygame.Rect(pos, rectsize)
				img = pygame.Surface.subsurface(self.source_image, rect)
				img = pygame.transform.smoothscale(img, tilesize)
				arrow_parts.append(img)

		self.arrow = {
			'horizontal': arrow_parts[1],
			'vertical': arrow_parts[4],
			'topleft': arrow_parts[0],
			'topright': arrow_parts[3],
			'bottomleft': arrow_parts[12],
			'bottomright': arrow_parts[15],
			'up': arrow_parts[5],
			'down': arrow_parts[10],
			'left': arrow_parts[9],
			'right': arrow_parts[6],
		}

	def get_arrow_part(self, coord):
		index = self.path.index(coord)
		a = self.path[index - 1] if index - 1 >= 0 else self.source
		b = self.path[index]
		c = self.path[index + 1] if (index + 1) < len(self.path) else None

		if c is None:
			ax, ay = a
			bx, by = b
			if bx == ax + 1:
				return self.arrow['right']
			elif bx == ax - 1:
				return self.arrow['left']
			elif by == ay + 1:
				return self.arrow['down']
			elif by == ay - 1:
				return self.arrow['up']
		else:
			ax, ay = a
			bx, by = b
			cx, cy = c
			if ax == bx == cx:
				return self.arrow['vertical']
			elif ay == by == cy:
				return self.arrow['horizontal']

			elif (ax == bx and ay < by and bx < cx and by == cy) or (cx == bx and by == ay and cy < by and bx < ax):
				return self.arrow['bottomleft']

			elif (ax == bx and ay < by and bx > cx and by == cy) or (ax < bx and ay == by and bx == cx and by > cy):
				return self.arrow['bottomright']

			elif (ax == bx and ay > by and bx > cx and by == cy) or (ax < bx and ay == by and bx == cx and by < cy):
				return self.arrow['topright']

			elif (ax == bx and ay > by and bx < cx and by == cy) or (ax > bx and ay == by and bx == cx and by < cy):
				return self.arrow['topleft']

			else:
				raise ValueError("ArrowError: " + str((a, b, c)))


class Pathfinder(object):
	"""Cached pathfinder"""
	def __init__(self, _map):
		self.map = _map
		self.w, self.h = self.map.w, self.map.h
		self.reset()

	def reset(self):
		self.source = None  # dijkstra executed with this node as source
		self.target = None  # shortest path target
		self.shortest = None  # shortest path output
		self.max_distance = None
		self.dist = None  # results of dijkstra
		self.prev = None

	def __set_source(self, source):
		"""
		Implementation of Dijkstra's Algorithm.
		See https://en.wikipedia.org/wiki/Dijkstra%27s_algorithm for
		reference.
		This method computes the distance of every node of the map from
		a given source node.
		"""
		self.shortest = None
		self.source = source

		# Unknown distance function from source to v
		self.dist = {(x, y): float('inf') for y in range(self.h) for x in range(self.w)}
		# Previous node in optimal path from source initialization
		self.prev = {(x, y): None for y in range(self.h) for x in range(self.w)}

		self.dist[source] = 0  # Distance from source to source

		# All nodes initially in Q (unvisited nodes)
		Q = [v for v in self.dist]

		source_unit = self.map[source].unit

		while Q:
			min_dist = self.dist[Q[0]]
			u = Q[0]

			for el in Q:
				if self.dist[el] < min_dist:
					min_dist = self.dist[el]
					u = el  #  Source node in first case

			Q.remove(u)

			# where v has not yet been removed from Q.
			for v in self.map.neighbors(u):
				alt = self.dist[u] + self.map[v].moves
				if alt < self.dist[v]:
					# A shorter path to v has been found
					if self.map.is_obstacle(v, source_unit):
						# v is an obstacle set infinite distance (unreachable)
						self.dist[v] = float('inf')
						# we still want to be able to find a path
						if not self.prev[v]:
							self.prev[v] = [(alt, u)]
						else:  # keep the shortest first
							heapq.heappush(self.prev[v], (alt, u))
					else:
						self.dist[v] = alt
						self.prev[v] = u

	def __set_target(self, target, max_distance=float('inf')):
		"""
		This method sets the target node and the maximum distance. The
		computed path total cost will not exceed the maximim distance.
		The shortest path between target and source previously specified
		with __set_source is returned as a list.
		"""
		self.max_distance = max_distance
		S = []
		u = self.target = target

		# Construct the shortest path with a stack S
		while self.prev[u] is not None:
			if self.dist[u] <= max_distance:
				S.insert(0, u)  # Push the vertex onto the stack
			try:
				u = self.prev[u][0][1]  # get the shorter path
			except TypeError:
				u = self.prev[u]  # Traverse from target to source

		if S and self.map[target].unit and not self.map.is_obstacle(target, self.map[self.source].unit):
			del S[-1]

		self.shortest = S
		return S

	def shortest_path(self, source, target, max_distance=float('inf')):
		if self.source != source:
			self.__set_source(source)
			self.__set_target(target, max_distance)
		elif self.target != target or self.max_distance != max_distance:
			self.__set_target(target, max_distance)
		return self.shortest

	def area(self, source, max_distance):
		if self.source != source:
			self.__set_source(source)
			self.target = None
			self.shortest = None
		h, w = range(self.h), range(self.w)
		return [(i, j) for j in h for i in w if self.dist[(i, j)] <= max_distance]


class Map(object):
	"""
	This class should handle every aspect related to the Map in Ice Emblem.
	"""

	def __init__(self, map_path, screen_size, units_manager):
		"""
		Loads a .tmx tilemap, initializes layers like sprites, cursor,
		arrow, highlight. It also generate a cost matrix to be used by
		the Path class.
		"""
		self.tilemap = tmx.load(map_path, (screen_size[0] - 200, screen_size[1]))
		self.tw, self.th = self.tile_size = (self.tilemap.tile_width, self.tilemap.tile_height)
		self.w, self.h = self.tilemap.width, self.tilemap.height

		self.terrains = {}
		self.sprites = tmx.SpriteLayer()

		for obj in self.tilemap.layers['Sprites'].objects:
			if obj.type == 'unit':
				try:
					unit = units_manager.get_units(name=obj.name)[0]
					unit.coord = obj.px // self.tw, obj.py // self.th
				except IndexError:
					pass
				else:
					team = units_manager.get_team(unit.color)
					UnitSprite(self.tile_size, obj, unit, team, self.sprites)

		for layer in reversed(self.tilemap.layers):
			try:
				print(layer)
				for cell in layer:
					try:
						coord = cell.px // self.tw, cell.py // self.th
						units = units_manager.get_units(coord=coord)
						unit = units[0] if units else None
						if coord not in self.terrains:
							self.terrains[coord] = Terrain(cell.tile, unit)
					except AttributeError:
						pass
			except TypeError:
				pass

		self.units_manager = units_manager

		cursor_layer = tmx.SpriteLayer()
		self.cursor = Cursor(self.tilemap, os.path.join('images', 'cursor.png'), cursor_layer)

		arrow_layer = tmx.SpriteLayer()
		self.arrow = Arrow((self.tilemap.px_width, self.tilemap.px_height), os.path.join('images', 'arrow.png'), self.tile_size, arrow_layer)

		highlight_layer = tmx.SpriteLayer()
		self.highlight = CellHighlight(self.tilemap, highlight_layer)

		self.tilemap.layers.append(highlight_layer)
		self.tilemap.layers.append(self.sprites)
		self.tilemap.layers.append(arrow_layer)
		self.tilemap.layers.append(cursor_layer)

		self.tilemap.set_focus(0, 0)

		self.prev_sel = None
		self.curr_sel = None
		self.move_area = []
		self.attack_area = []

		self.move_x, self.move_y = 0, 0
		self.path = Pathfinder(self)

	def __getitem__(self, coord):
		return self.terrains[coord]

	def is_obstacle(self, coord, unit):
		terrain = self.terrains[coord]
		try:
			return self.units_manager.are_enemies(unit, terrain.unit)
		except AttributeError:
			unit_allowed = unit.get_allowed_terrains()
			for allowed in terrain.allowed:
				if allowed == _('any'):
					return False
				elif allowed == _('none'):
					return True
				if allowed in unit_allowed:
					return False
			return True

	def check_coord(self, coord):
		x, y = coord
		return 0 <= x < self.w and 0 <= y < self.h

	def neighbors(self, coord):
		"""
		Returns a list containing all existing neighbors of a node.
		coord must be a valid coordinate i.e. self.check_coord(coord).
		"""
		if not self.check_coord(coord):
			raise ValueError("Invalid coordinates")
		x, y = coord
		n = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
		ret = [c for c in n if self.check_coord(c)]

		return ret

	def screen_resize(self, screen_size):
		viewport_size = (screen_size[0] - 200, screen_size[1])
		self.tilemap.viewport = pygame.Rect(self.tilemap.viewport.topleft, viewport_size)
		self.tilemap.view_w, self.tilemap.view_h = viewport_size

	def mouse2cell(self, cursor_coord):
		"""mouse position to map index."""
		x, y = cursor_coord
		map_index = self.tilemap.index_at(x, y)
		if self.check_coord(map_index):
			return map_index
		else:
			raise ValueError('(%d:%d) Cursor out of map')

	def move(self, unit, new_coord):
		"""
		This method moves a unit from a node to another one. If the two
		coordinates are the same no action is performed.
		"""
		if unit.coord != new_coord:
			if self.get_unit(new_coord) is not None:
				raise ValueError("Destination %s is already occupied by another unit" % str(new_coord))
			self.terrains[unit.coord].unit = None
			self.terrains[new_coord].unit = unit
			self.find_sprite(unit=unit).update(new_coord)
			print(_('Unit %s moved from %s to %s') % (unit.name, unit.coord, new_coord))
			unit.coord = new_coord

	def kill_unit(self, **kwargs):
		coord = kwargs['coord'] if 'coord' in kwargs else kwargs['unit'].coord
		self.terrains[coord].unit = None
		sprite = self.find_sprite(**kwargs)
		self.sprites.remove(sprite)

	def update_move_area(self, coord):
		"""
		Updates the area which will be highlighted on the map to show
		which nodes can be reached by the selected unit.
		"""
		unit = self.get_unit(coord)
		self.move_area = self.path.area(coord, unit.move)

	def get_unit(self, coord):
		return self.terrains[coord].unit

	def find_sprite(self, **kwargs):
		for sprite in self.sprites:
			for attr in kwargs:
				if getattr(sprite, attr) == kwargs[attr]:
					return sprite

	def update_attack_area(self, coord):
		"""
		Updates the area which will be highlighted on the map to show
		how far the selected unit can attack.
		"""
		weapon_range = self.get_unit(coord).get_weapon_range()
		self.attack_area = []

		for (x, y) in self.move_area:
			for i in range(x - weapon_range, x + weapon_range + 1):
				for j in range(y - weapon_range, y + weapon_range + 1):
					if (i, j) not in self.move_area and (i, j) not in self.attack_area:
						if utils.distance((x, y), (i, j)) <= weapon_range:
							self.attack_area.append((i, j))

	def update_arrow(self, target):
		if self.curr_sel and target:
			if target in self.move_area:
				path = self.path.shortest_path(self.curr_sel, target, self.get_unit(self.curr_sel).move)
				self.arrow.update(path, self.curr_sel)
		else:
			self.arrow.update([])

	def update_highlight(self):
		played = [u.coord for u in self.units_manager.active_team.list_played()]
		self.highlight.update(self.curr_sel, self.move_area, self.attack_area, played)

	def area(self, c, r):
		x, y = c
		a = [(i, j) for i in range(x - r, x + r + 1)
					for j in range(y - r, y + r + 1)
					if self.check_coord((i, j))
					and utils.distance((x, y), (i, j)) <= r]
		return a

	def nearby_enemies(self, unit):
		"""
		Returns a list of coordinates of near enemies that can be
		attacked without having to move.
		"""
		area = self.area(unit.coord, unit.get_weapon_range())
		def f(c):
			c_unit = self.get_unit(c)
			return c_unit and self.units_manager.are_enemies(c_unit, unit)
		nearby_list = [c for c in area if f(c)]
		return nearby_list

	def reset_selection(self):
		logging.debug(_('Selection reset'))
		self.curr_sel = None
		self.prev_sel = None
		self.move_area = []
		self.attack_area = []
		self.arrow.update([])
		self.update_highlight()

	def can_selection_move(self):
		prev_unit = self.get_unit(self.prev_sel)
		curr_unit = self.get_unit(self.curr_sel)

		return (prev_unit is not None and not prev_unit.played and
			self.units_manager.active_team.is_mine(prev_unit) and
			self.curr_sel in self.move_area)

	def sel_distance(self):
		return distance(self.curr_sel, self.prev_sel)

	def can_selection_attack(self):
		prev_unit = self.get_unit(self.prev_sel)
		curr_unit = self.get_unit(self.curr_sel)
		active_team = self.units_manager.active_team

		return (prev_unit is not None and not prev_unit.played and
			active_team.is_mine(prev_unit) and
			curr_unit is not None and
			not active_team.is_mine(curr_unit) and
			self.sel_distance() <= prev_unit.get_weapon_range())

	def handle_click(self, event):
		if event.button == 1:
			try:
				coord = self.mouse2cell(event.pos)
			except ValueError:
				return []
			ret = self.select(coord)
			self.update_highlight()
			return ret
		elif event.button == 3:
			self.reset_selection()
			return []

	def handle_mouse_motion(self, event):
		try:
			coord = self.mouse2cell(event.pos)
			self.update_arrow(coord)
		except ValueError:
			pass
		self.cursor.update(event)

		x, y = event.pos
		border = 50
		speed = 5
		if x < border:
			self.move_x = -speed
		elif x > self.tilemap.view_w - border:
			self.move_x = speed
		else:
			self.move_x = 0

		if y < border:
			self.move_y = -speed
		elif y > self.tilemap.view_h - border:
			self.move_y = speed
		else:
			self.move_y = 0

	def draw(self, surf):
		self.sprites.update()
		fx = self.tilemap.fx + self.move_x
		fy = self.tilemap.fy + self.move_y
		if fx != self.tilemap.fx or fy != self.tilemap.fy:
			self.tilemap.set_focus(fx, fy)

		self.tilemap.draw(surf)

	def handle_keyboard(self, event):
		self.cursor.update(event)
		self.update_arrow(self.cursor.coord)
		self.tilemap.set_focus(self.cursor.rect.x, self.cursor.rect.y)

		if event.key == pygame.K_SPACE:
			ret = self.select(self.cursor.coord)
			self.update_highlight()
			return ret

	def select(self, coord):
		active_team = self.units_manager.active_team
		self.curr_sel = coord
		self.arrow.update([])

		if self.prev_sel is None:
			unit = self.get_unit(coord)
			if unit is None or unit.played:
				self.move_area = []
				self.attack_area = []
			else:
				self.update_move_area(coord)
				self.update_attack_area(coord)
			self.prev_sel = self.curr_sel
		else:
			prev_unit = self.get_unit(self.prev_sel)
			curr_unit = self.get_unit(self.curr_sel)

			if prev_unit is not None and curr_unit is not None:
				if prev_unit == curr_unit and not prev_unit.played and active_team.is_mine(prev_unit):
					enemies_nearby = len(self.nearby_enemies(self.get_unit(self.curr_sel)))
					if enemies_nearby > 0:
						return [(_("Attack"), self.attack_callback), (_("Wait"), self.wait_callback)]
					else:
						return[(_("Wait"), self.wait_callback)]
				else:
					self.prev_sel = self.curr_sel
					self.update_move_area(self.curr_sel)
					self.update_attack_area(self.curr_sel)
			elif self.can_selection_move():
				self.move(self.get_unit(self.prev_sel), self.curr_sel)
				enemies_nearby = len(self.nearby_enemies(self.get_unit(self.curr_sel)))
				if enemies_nearby > 0:
					return [(_("Attack"), self.attack_callback), (_("Wait"), self.wait_callback)]
				else:
					return[(_("Wait"), self.wait_callback)]
			else:
				self.reset_selection()
				self.curr_sel = self.prev_sel = coord

				if curr_unit is not None and not curr_unit.played:
					self.update_move_area(coord)
					self.update_attack_area(coord)
		return []

	def wait_callback(self):
		unit = self.get_unit(self.curr_sel)
		unit.played = True
		self.reset_selection()

	def attack_callback(self):
		unit = self.get_unit(self.curr_sel)
		self.move_area = []
		self.attack_area = self.nearby_enemies(self.get_unit(self.curr_sel))
		self.update_highlight()

	def rollback_callback(self):
		self.move(self.get_unit(self.curr_sel), self.prev_sel)
		self.reset_selection()

	def is_attack_click(self, mouse_pos):
		try:
			x, y = self.mouse2cell(mouse_pos)
		except ValueError:
			return False

		return (x, y) in self.attack_area

	def is_enemy_cursor(self):
		return self.cursor.coord in self.attack_area
