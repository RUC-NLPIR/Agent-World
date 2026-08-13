# MercantileCare Operations Hub

MercantileCare Operations Hub is a retail commerce support service that exposes product catalog and order/customer operations for lookup and post-purchase changes.

## Datastore

### `products.json` — object of 50 records keyed by identifier
Holds the product catalog with per-variant option/availability/price data so the service can look up product and inventory details when assisting with shopping and fulfillment.
Keys look like: 9523456873, 4760268021, 6938111410

- `name` — string
- `product_id` — string
- `variants` — object
  each record in `variants` has:
  - `item_id` — string
  - `options` — object
    each record in `options` has:
    - `color` — string
    - `size` — string
    - `material` — string
    - `style` — string — one of crew neck, v-neck
    - `screen size` — string
    - `processor` — string — one of i5, i7, i9
    - `ram` — string — one of 16GB, 32GB, 8GB
    - `storage` — string
    - `sole` — string — one of EVA, rubber
    - `RAM` — string — one of 4GB, 6GB, 8GB
    - `compartment` — string — one of camera, hydration, laptop
    - `capacity` — string
    - `type` — string
    - `features` — string
    - `brightness` — string — one of 100W equivalent, 60W equivalent, 75W equivalent, high, low, medium
    - `power source` — string — one of AC adapter, USB, battery
    - `cover type` — string — one of hard cover, soft cover
    - `frame color` — string — one of black, brown, silver
    - `lens color` — string — one of black, blue, brown, green
    - `lens type` — string — one of non-polarized, polarized
    - `frame material` — string — one of metal, plastic
    - `strap material` — string — one of leather, metal, silicone
    - `dial color` — string — one of black, blue, white
    - `speed settings` — string — one of high, low
    - `battery type` — string — one of AA batteries, rechargeable
    - `thickness` — string — one of 4mm, 5mm, 6mm
    - `battery life` — string — one of 10 hours, 20 hours, 4 hours, 6 hours, 8 hours
    - `water resistance` — string — one of IPX4, IPX7, no, not resistant, yes
    - `sensor type` — string — one of laser, optical
    - `connectivity` — string
    - `resolution` — string — one of 1080p, 20MP, 24MP, 2K, 30MP, 4K, 5K
    - `waterproof` — string — one of no, yes
    - `length` — string — one of 100ft, 25ft, 28 inch, 31 inch, 34 inch, 50ft
    - `output` — string — one of USB-A, USB-C, Wireless
    - `field of view` — string — one of 110 degrees, 130 degrees, 160 degrees
    - `switch type` — string — one of clicky, linear, tactile
    - `backlight` — string — one of RGB, none, white
    - `compatibility` — string — one of Amazon Alexa, Apple HomeKit, Google Assistant
    - `zipper` — string — one of full, half
    - `diameter` — string — one of 10 inches, 12 inches, 14 inches
  - `available` — boolean
  - `price` — number

### `orders.json` — object of 1000 records keyed by identifier
Holds customer order records (including purchaser and delivery/payment context) so the service can retrieve order details and support actions like cancellation or exchanges.
Keys look like: #W2611340, #W4817420, #W6304490
Lifecycle field `status`, states observed: cancelled, delivered, pending, processed

- `order_id` — string
- `user_id` — string — references users.id
- `address` — object
  each record in `address` has:
  - `address1` — string
  - `address2` — string
  - `city` — string
  - `country` — string
  - `state` — string
  - `zip` — string
- `items` — array
  each record in `items` has:
  - `name` — string
  - `product_id` — string
  - `item_id` — string
  - `price` — number
  - `options` — object
    each record in `options` has:
    - `capacity` — string
    - `material` — string
    - `color` — string
    - `armrest` — string — one of adjustable, fixed, none
    - `backrest height` — string — one of high-back, standard
    - `height` — string — one of 3 ft, 4 ft, 5 ft, 6 ft
    - `resolution` — string — one of 1080p, 20MP, 24MP, 2K, 30MP, 4K, 5K
    - `waterproof` — string — one of no, yes
    - `size` — string
    - `deck material` — string — one of bamboo, maple, plastic
    - `length` — string — one of 100ft, 25ft, 28 inch, 31 inch, 34 inch, 50ft
    - `design` — string — one of custom, graphic, plain
    - `compatibility` — string — one of Amazon Alexa, Apple HomeKit, Google Assistant
    - `room size` — string — one of large, medium, small
    - `filter type` — string — one of HEPA, carbon, ionic
    - `features` — string
    - `weight range` — string — one of 30-50 lbs, 5-25 lbs, 55-75 lbs
    - `set type` — string — one of adjustable, fixed
    - `scent family` — string — one of fresh, oriental, woody
    - `gender` — string — one of men, unisex, women
    - `pieces` — string — one of 1000, 1500, 2000, 500
    - `theme` — string — one of animals, art, fantasy, landscape
    - `difficulty level` — string — one of beginner, expert, intermediate
    - `style` — string — one of crew neck, v-neck
    - `skin tone` — string — one of dark, light, medium
    - `kit size` — string — one of basic, professional
    - `brand` — string — one of Brand A, Brand B, Brand C
    - `screen size` — string
    - `storage` — string
    - `pressure` — string — one of 15 bar, 19 bar, 9 bar
    - `type` — string
    - `stovetop compatibility` — string — one of electric, gas, induction
    - `battery life` — string — one of 10 hours, 20 hours, 4 hours, 6 hours, 8 hours
    - `water resistance` — string — one of IPX4, IPX7, no, not resistant, yes
    - `bagged/bagless` — string — one of bagged, bagless
    - `speed settings` — string — one of high, low
    - `battery type` — string — one of AA batteries, rechargeable
    - `output` — string — one of USB-A, USB-C, Wireless
    - `frame size` — string — one of large, medium, small
    - `switch type` — string — one of clicky, linear, tactile
- `status` — string — one of cancelled, delivered, pending, processed
- `fulfillments` — array
  each record in `fulfillments` has:
  - `tracking_id` — array
  - `item_ids` — array
- `payment_history` — array
  each record in `payment_history` has:
  - `transaction_type` — string — one of payment, refund
  - `amount` — number
  - `payment_method_id` — string

### `users.json` — object of 500 records keyed by identifier
Keys look like: noah_brown_6181, ivan_santos_6635, anya_garcia_3271

- `user_id` — string
- `name` — object
  each record in `name` has:
  - `first_name` — string
  - `last_name` — string
- `address` — object
  each record in `address` has:
  - `address1` — string
  - `address2` — string
  - `city` — string
  - `country` — string
  - `state` — string
  - `zip` — string
- `email` — string
- `payment_methods` — object
  each record in `payment_methods` has:
  - `source` — string — one of credit_card, gift_card, paypal
  - `id` — string
  - `brand` — string — one of mastercard, visa
  - `last_four` — string
  - `balance` — number
- `orders` — array
